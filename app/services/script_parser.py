"""GPT-4o 대본 파싱 서비스.

공개 API:
  parse_script(script_text)       — 텍스트 대본 파싱
  parse_script_pdf(pdf_bytes, ...) — PDF 직접 파싱 (Responses API)

내부 모듈:
  parse_cache      — 캐시 I/O
  parse_normalizer — 텍스트·이름 정규화, 청크 분할, 결과 병합
  parse_enricher   — LLM 기반 meta·line enrichment
"""

import base64
import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

from app.core.config import client, OPENAI_PARSE_FAST_MODEL, OPENAI_PARSE_PDF_MODEL
from app.prompts.templates import (
    ENRICH_LINES_SYSTEM,
    ENRICH_META_SYSTEM,
    PARSE_FAST_SYSTEM,
)
from app.services.parse_cache import load_cache, save_cache
from app.services.parse_enricher import enrich_lines, enrich_meta
from app.services.parse_normalizer import (
    CHUNK_SIZE,
    _split_into_chunks,
    _strip_json_fences,
    build_alias_map,
    merge_results,
    normalize_script_text,
    remap_result,
)


class PDFTruncationError(RuntimeError):
    """Responses API 응답이 max_output_tokens 한도로 잘렸을 때 발생."""
    pass


# ── 상수 ─────────────────────────────────────────────────────────

# 이 길이 이하는 단일 호출 사용 (청크 오버헤드 불필요)
CHUNK_THRESHOLD = 3_500

# fast parse용 output token 상한
MAX_TOKENS = 6_000

# 병렬 청크 처리 워커 수
MAX_WORKERS = 4

# JSON 오류 청크 fallback 재분할 크기
FALLBACK_CHUNK_SIZE = CHUNK_SIZE // 2  # 2_000자

# PDF direct parse sanity check
MIN_LINES_PER_PAGE = 2
MIN_PAGES_FOR_LINE_CHECK = 5

# 프롬프트 변경 시 캐시 자동 무효화용 해시
_COMBINED_PROMPTS = PARSE_FAST_SYSTEM + ENRICH_META_SYSTEM + ENRICH_LINES_SYSTEM
_PROMPT_HASH = hashlib.md5(_COMBINED_PROMPTS.encode()).hexdigest()[:8]


# ── 공개 API ─────────────────────────────────────────────────────

def parse_script_pdf(pdf_bytes: bytes, filename: str = "script.pdf", total_pages: int = 0) -> dict:
    """PDF를 base64 인라인으로 Responses API에 직접 전달해 파싱한다."""
    t_total = time.time()
    pdf_hash = hashlib.md5(pdf_bytes).hexdigest()
    cache_key = hashlib.md5(f"{_PROMPT_HASH}:{pdf_hash}".encode()).hexdigest()
    cached = load_cache(cache_key)
    if cached is not None:
        logger.info(f"[PDF-Direct] 캐시 히트: {cache_key[:8]}... ({total_pages}페이지)")
        return cached

    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    instructions_with_json = "Output valid json only. No text outside json.\n\n" + PARSE_FAST_SYSTEM
    user_text = "이 대본을 분석해주세요. Output must be a single valid json object. No text outside json."

    logger.info(f"[PDF-Direct] Responses API 호출 중... ({len(pdf_bytes):,}B, {total_pages}페이지)")
    t = time.time()
    response = client.responses.create(
        model=OPENAI_PARSE_PDF_MODEL,
        instructions=instructions_with_json,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": filename,
                        "file_data": f"data:application/pdf;base64,{pdf_b64}",
                    },
                    {"type": "input_text", "text": user_text},
                ],
            }
        ],
        text={"format": {"type": "json_object"}},
        temperature=0.3,
        max_output_tokens=65_536,
    )
    usage = getattr(response, "usage", None)
    out_tokens = getattr(usage, "output_tokens", "?") if usage else "?"
    status = getattr(response, "status", None)
    logger.info(f"[PDF-Direct] 완료 ({time.time()-t:.1f}s) — status={status} output_tokens={out_tokens}")

    if status == "incomplete":
        raise PDFTruncationError(
            f"PDF direct parse 잘림 (output_tokens={out_tokens}). text extraction fallback으로 재시도합니다."
        )

    raw = _strip_json_fences(response.output_text or "{}")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(
            "[PDF-Direct] JSON 파싱 실패 (len=%d): %s\n  원문 앞 300자: %r\n  원문 뒤 200자: %r",
            len(raw), e, raw[:300], raw[-200:],
        )
        raise PDFTruncationError(
            f"PDF direct parse JSON 오류: {e}. text extraction fallback으로 전환합니다."
        )

    n_lines = len(result.get("lines") or [])
    logger.info(f"[PDF-Direct] 파싱 완료 — lines={n_lines}, pages={total_pages}")

    if total_pages >= MIN_PAGES_FOR_LINE_CHECK:
        min_expected = total_pages * MIN_LINES_PER_PAGE
        if n_lines < min_expected:
            logger.warning(
                "[PDF-Direct] 라인 수 부족 (%d줄 < %dp × %d) — 모델이 일찍 종료된 것으로 판단, text fallback으로 전환",
                n_lines, total_pages, MIN_LINES_PER_PAGE,
            )
            raise PDFTruncationError(
                f"PDF direct parse 라인 수 부족 ({n_lines}줄 / {total_pages}페이지). "
                f"text extraction fallback으로 전환합니다."
            )

    alias_map = build_alias_map(result.get("characters") or [])
    result = remap_result(result, alias_map)

    t = time.time()
    result = enrich_meta(result)
    logger.info(f"[PDF-Direct] enrich_meta: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")
    t = time.time()
    result = enrich_lines(result)
    logger.info(f"[PDF-Direct] enrich_lines: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")

    save_cache(cache_key, result)
    logger.info(f"[PDF-Direct] 총 소요시간: {time.time()-t_total:.1f}s")
    return result


def parse_script(script_text: str) -> dict:
    """대본 텍스트를 GPT-4o로 파싱해 구조화된 dict 반환.

    1. MD5 캐시 히트 → 즉시 반환
    2. Fast chunked parse — MAX_WORKERS 병렬 처리
    3. 청크 병합 후 단일 enrich_meta 호출 (character_analysis + relationships)
    4. 결과 캐시 저장
    """
    t_total = time.time()

    t = time.time()
    script_text = normalize_script_text(script_text)
    total_chars = len(script_text)
    logger.info(f"[Parser] normalize: {time.time()-t:.2f}s ({total_chars}자)")

    cache_key = hashlib.md5(f"{_PROMPT_HASH}:{script_text}".encode()).hexdigest()
    cached = load_cache(cache_key)
    if cached is not None:
        logger.info(f"[Parser] 캐시 히트: {cache_key[:8]}... ({total_chars}자, prompt={_PROMPT_HASH})")
        return cached

    if total_chars <= CHUNK_THRESHOLD:
        logger.info(f"[Parser] 경로: single  | 입력: {total_chars}자")
        t = time.time()
        result = _parse_single(script_text)
        logger.info(f"[Parser] single fast parse: {time.time()-t:.1f}s")
        alias_map = build_alias_map(result.get("characters") or [])
        result = remap_result(result, alias_map)
        t = time.time()
        result = enrich_meta(result)
        logger.info(f"[Parser] single enrich_meta: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")
        t = time.time()
        result = enrich_lines(result)
        logger.info(f"[Parser] single enrich_lines: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")
        save_cache(cache_key, result)
        logger.info(f"[Parser] 총 소요시간: {time.time()-t_total:.1f}s")
        return result

    t = time.time()
    chunks = _split_into_chunks(script_text)
    logger.info("[Parser] chunk split: %.2fs | %d개 청크 (크기: %s)", time.time()-t, len(chunks), [len(c) for c in chunks])

    t = time.time()
    chunk_results: dict[int, dict] = {}
    failed_chunks: list[int] = []
    recovered_chunks: list[int] = []

    def _collect(result: dict | None, chunk_1based: int, chunk_0based: int) -> None:
        if result is None:
            failed_chunks.append(chunk_1based)
        else:
            if result.pop("_recovered_by_fallback", False):
                recovered_chunks.append(chunk_1based)
            chunk_results[chunk_0based] = result

    first_result = _parse_chunk_with_retry(chunks[0], 0, len(chunks))
    _collect(first_result, 1, 0)
    initial_chars = (chunk_results[0].get("characters") or []) if 0 in chunk_results else []
    if initial_chars:
        logger.info(f"[Parser] 초기 캐릭터 추출: {initial_chars}")

    if len(chunks) > 1:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_idx = {
                executor.submit(_parse_chunk_with_retry, chunk, i, len(chunks), initial_chars): i
                for i, chunk in enumerate(chunks[1:], 1)
            }
            for future in as_completed(future_to_idx):
                i = future_to_idx[future]
                _collect(future.result(), i + 1, i)

    n_total = len(chunks)
    n_ok = len(chunk_results) - len(recovered_chunks)
    logger.info(
        "[Parser] chunk parse 완료 (%.1fs) — 전체 %d청크: 정상 %d, 복구(fallback) %d, 실패 %d",
        time.time()-t, n_total, n_ok, len(recovered_chunks), len(failed_chunks),
    )

    results = [chunk_results[i] for i in sorted(chunk_results.keys())]

    if not results:
        raise RuntimeError(f"모든 청크 파싱 실패 ({len(chunks)}개). 유효한 결과가 없습니다.")

    t = time.time()
    try:
        merged = merge_results(results)
    except Exception as e:
        raise RuntimeError(f"청크 병합 실패: {e}") from e
    logger.info(f"[Parser] merge: {time.time()-t:.2f}s")

    alias_map = build_alias_map(merged.get("characters") or [])
    merged = remap_result(merged, alias_map)

    if failed_chunks or recovered_chunks:
        merged["partial_failure"] = {
            "failed_chunks": failed_chunks,
            "recovered_chunks": recovered_chunks,
            "total_chunks": len(chunks),
        }
        if failed_chunks:
            logger.warning(f"[Parser] 부분 실패: {len(failed_chunks)}/{len(chunks)} 청크 실패 (청크: {failed_chunks})")
        if recovered_chunks:
            logger.info(f"[Parser] fallback 복구: {len(recovered_chunks)}개 청크 복구 성공 (청크: {recovered_chunks})")

    logger.info("[Parser] 병합 완료 - 캐릭터 %d명, 대사 %d줄", len(merged['characters']), len(merged['lines']))

    t = time.time()
    merged = enrich_meta(merged)
    logger.info(f"[Parser] enrich_meta: {time.time()-t:.1f}s — lines={len(merged.get('lines') or [])}")
    t = time.time()
    merged = enrich_lines(merged)
    logger.info(f"[Parser] enrich_lines: {time.time()-t:.1f}s — lines={len(merged.get('lines') or [])}")

    save_cache(cache_key, merged)
    logger.info(f"[Parser] 총 소요시간: {time.time()-t_total:.1f}s")
    return merged


# ── 청크 파싱 (내부) ─────────────────────────────────────────────

def _classify_json_failure(raw: str, input_len: int, finish_reason: str, e: json.JSONDecodeError) -> str:
    """JSON 파싱 실패 원인을 분류하고 진단 로그를 출력한다."""
    err_lower = str(e).lower()
    stripped = raw.lstrip()

    has_fence          = "```" in raw
    has_closing_brace  = "}" in raw
    is_length_cut      = finish_reason == "length"
    unterminated       = "unterminated string" in err_lower
    commentary_prefix  = bool(stripped) and stripped[0] not in ('{', '[', '"')

    if is_length_cut:
        label = "truncation"
    elif unterminated:
        label = "unterminated_str"
    elif has_fence:
        label = "fence_leaked"
    elif commentary_prefix:
        label = "commentary_prefix"
    elif not has_closing_brace:
        label = "no_closing_brace"
    elif not stripped:
        label = "empty_response"
    else:
        label = "malformed_json"

    logger.warning(
        "[Parser] JSON 실패 분류: [%s]\n"
        "  finish_reason  : %r\n"
        "  input_length   : %d자\n"
        "  raw_length     : %d자\n"
        "  has_fence      : %s\n"
        "  has_closing_}  : %s\n"
        "  raw_head       : %r\n"
        "  raw_tail       : %r\n"
        "  json_error     : %s",
        label, finish_reason, input_len, len(raw),
        has_fence, has_closing_brace, raw[:120], raw[-80:], e,
    )
    return label


def _parse_single(text: str, known_characters: list[str] | None = None) -> dict:
    """단일 텍스트를 GPT-4o 1회 호출로 구조적 파싱 (actor analysis 없음).

    known_characters: 앞 청크에서 추출한 캐릭터 이름 목록.
    finish_reason='length': 출력 토큰 한도 초과 → JSON 잘림 위험.
    JSON 파싱 실패 시 _classify_json_failure()로 원인 분류 후 re-raise.
    """
    user_content = f"다음 대본을 분석해주세요:\n\n{text}"
    if known_characters:
        chars_str = ", ".join(known_characters)
        user_content = (
            f"등장인물 (이 이름으로 시작하는 줄은 반드시 dialogue로 분류하세요): {chars_str}\n\n"
            + user_content
        )

    response = client.chat.completions.create(
        model=OPENAI_PARSE_FAST_MODEL,
        messages=[
            {"role": "system", "content": PARSE_FAST_SYSTEM},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.3,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
    )

    choice = response.choices[0]
    finish_reason = choice.finish_reason
    raw = choice.message.content or ""

    if finish_reason != "stop":
        logger.warning("[Parser] WARN finish_reason='%s' (입력 %d자) - JSON이 중간에 잘렸을 수 있음", finish_reason, len(text))

    raw_original_len = len(raw)
    raw = _strip_json_fences(raw)
    if len(raw) != raw_original_len:
        logger.info(f"[Parser] preprocessing: {raw_original_len}자 → {len(raw)}자 (fence/선행텍스트 제거)")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        label = _classify_json_failure(raw, len(text), finish_reason, e)
        e.classification = label  # type: ignore[attr-defined]
        raise


def _parse_chunk_json_fallback(chunk: str, idx: int, total: int, known_characters: list[str] | None) -> dict | None:
    """JSON 오류 청크를 FALLBACK_CHUNK_SIZE로 재분할해 재시도. 성공분만 병합해 반환."""
    subchunks = _split_into_chunks(chunk, max_chars=FALLBACK_CHUNK_SIZE)
    logger.info(
        "[Parser] 청크 %d/%d fallback 재분할: %d자(원본 %d자 기준) → %d개(%d자 기준)",
        idx+1, total, len(chunk), CHUNK_SIZE, len(subchunks), FALLBACK_CHUNK_SIZE,
    )
    results = []
    n_sub = len(subchunks)
    for part_num, part in enumerate(subchunks, 1):
        if not part:
            continue
        try:
            res = _parse_single(part, known_characters=known_characters)
            n = len(res.get("lines") or [])
            logger.info(f"[Parser] 청크 {idx+1}/{total} subchunk {part_num}/{n_sub} 성공 — lines={n}")
            results.append(res)
        except Exception as sub_e:
            label = getattr(sub_e, "classification", "")
            suffix = f" [{label}]" if label else ""
            logger.warning(f"[Parser] 청크 {idx+1}/{total} subchunk {part_num}/{n_sub} 실패{suffix}: {sub_e}")

    if not results:
        logger.warning(f"[Parser] 청크 {idx+1}/{total} subchunk 모두 실패 → 폐기")
        return None

    out = results[0] if len(results) == 1 else merge_results(results)
    n = len(out.get("lines") or [])
    logger.info(f"[Parser] 청크 {idx+1}/{total} subchunk {len(results)}/{n_sub}개 복구 완료 — lines={n}")
    out["_recovered_by_fallback"] = True
    return out


def _parse_chunk_with_retry(chunk: str, idx: int, total: int, known_characters: list[str] | None = None) -> dict | None:
    """단일 청크를 파싱한다. 실패 시 1회 재시도. None 반환 시 실패."""
    t = time.time()
    for attempt in range(2):
        try:
            result = _parse_single(chunk, known_characters=known_characters)
            n_lines = len(result.get("lines") or [])
            n_chars = len(result.get("characters") or [])
            logger.info(f"[Parser] 청크 {idx+1}/{total} 완료 ({time.time()-t:.1f}s) — lines={n_lines}, chars={n_chars}")
            return result
        except json.JSONDecodeError as e:
            label = getattr(e, "classification", "unknown")
            logger.warning(f"[Parser] 청크 {idx+1}/{total} JSON 오류 [{label}] → subchunk 분할 재시도")
            return _parse_chunk_json_fallback(chunk, idx, total, known_characters)
        except Exception as e:
            if attempt == 0:
                logger.warning(
                    "[Parser] 청크 %d/%d 실패 (재시도 중, len=%d자): %s: %s | preview=%r",
                    idx+1, total, len(chunk), type(e).__name__, e, chunk[:80],
                )
            else:
                logger.error(
                    "[Parser] 청크 %d/%d 최종 실패 (len=%d자): %s: %s",
                    idx+1, total, len(chunk), type(e).__name__, e,
                )
    return None
