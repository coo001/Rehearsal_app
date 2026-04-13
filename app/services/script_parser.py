"""GPT-4o 대본 파싱 서비스."""


class PDFTruncationError(RuntimeError):
    """Responses API 응답이 max_output_tokens 한도로 잘렸을 때 발생."""
    pass

import base64
import hashlib
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.core.config import (
    client,
    OPENAI_PARSE_FAST_MODEL,
    OPENAI_PARSE_PDF_MODEL,
    OPENAI_ENRICH_MODEL,
)
from app.prompts.templates import ENRICH_LINES_SYSTEM, ENRICH_META_SYSTEM, PARSE_FAST_SYSTEM, PARSE_SCRIPT_SYSTEM  # PARSE_SCRIPT_SYSTEM: PDF direct path에서 사용

# 단일 청크 최대 길이
# 4000자 기준 출력 ~5,400 tokens → MAX_TOKENS=6000 필요
CHUNK_SIZE = 4_000

# 이 길이 이하는 단일 호출 사용 (청크 오버헤드 불필요)
CHUNK_THRESHOLD = 3_500

# fast parse용 output token 상한
# 4000자 청크 → ~5,400 tokens; 3000자 청크도 ~4,100 → 기존 4096은 밀도 높은 대본에서 잘림 위험
MAX_TOKENS = 6_000

# 병렬 청크 처리 워커 수 — API rate limit 여유 있게 보수적으로 설정
MAX_WORKERS = 4

# JSON 오류 청크 fallback 재분할 크기 — 정상 경로 성능 유지, 실패 시에만 적용
FALLBACK_CHUNK_SIZE = CHUNK_SIZE // 2  # 2_000자

# PDF direct parse 결과 sanity check: 이 값 미만이면 parse 불완전으로 판단 → fallback
# 연극 대본 기준 최소 2줄/페이지는 매우 보수적 하한 (false positive 극소화)
# 5페이지 이상 PDF에만 적용 (짧은 연습 스크립트 false positive 방지)
MIN_LINES_PER_PAGE = 2
MIN_PAGES_FOR_LINE_CHECK = 5

# 파싱 결과 캐시 디렉토리
CACHE_DIR = Path("data/parse_cache")

# 파싱/enrichment 관련 모든 프롬프트 변경 시 자동 cache 무효화
_COMBINED_PROMPTS = PARSE_FAST_SYSTEM + ENRICH_META_SYSTEM + ENRICH_LINES_SYSTEM
_PROMPT_HASH = hashlib.md5(_COMBINED_PROMPTS.encode()).hexdigest()[:8]

# 라인 enrichment 배치 크기 (beat_goal/subtext/tts_direction)
ENRICH_LINES_BATCH_SIZE = 30
ENRICH_LINES_MAX_TOKENS = 2_500


def parse_script_pdf(pdf_bytes: bytes, filename: str = "script.pdf", total_pages: int = 0) -> dict:
    """PDF를 base64 인라인으로 Responses API에 직접 전달해 파싱한다.

    chat.completions는 file content type을 지원하지 않으므로
    Responses API(client.responses.create)로 base64 인라인 전달.
    Files API 업로드/삭제 없이 PDF 바이트를 직접 모델에 전달한다.
    """
    t_total = time.time()
    pdf_hash = hashlib.md5(pdf_bytes).hexdigest()
    cache_key = hashlib.md5(f"{_PROMPT_HASH}:{pdf_hash}".encode()).hexdigest()
    cached = _load_cache(cache_key)
    if cached is not None:
        print(f"[PDF-Direct] 캐시 히트: {cache_key[:8]}... ({total_pages}페이지)")
        return cached

    pdf_b64 = base64.b64encode(pdf_bytes).decode()

    # PARSE_FAST_SYSTEM: 라인당 ~50 tokens (actor analysis 없음)
    # PARSE_SCRIPT_SYSTEM은 라인당 ~93 tokens + character_analysis/relationships ~4500 tokens 고정 오버헤드
    # → 8192 max_output_tokens 기준 ~40줄만 출력됨 (20페이지 대본의 경우 ~1페이지에서 조기 종료)
    # PARSE_FAST_SYSTEM + _enrich_meta() 분리로 텍스트 경로와 동일한 전략 적용
    instructions_with_json = "Output valid json only. No text outside json.\n\n" + PARSE_FAST_SYSTEM
    user_text = "이 대본을 분석해주세요. Output must be a single valid json object. No text outside json."

    print(f"[PDF-Direct] Responses API 호출 중... ({len(pdf_bytes):,}B, {total_pages}페이지)")
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
    print(f"[PDF-Direct] 완료 ({time.time()-t:.1f}s) — status={status} output_tokens={out_tokens}")

    if status == "incomplete":
        raise PDFTruncationError(
            f"PDF direct parse 잘림 (output_tokens={out_tokens}). text extraction fallback으로 재시도합니다."
        )

    raw = _strip_json_fences(response.output_text or "{}")
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            f"[PDF-Direct] JSON 파싱 실패 (len={len(raw)}): {e}\n"
            f"[PDF-Direct] 원문 앞 300자: {raw[:300]!r}\n"
            f"[PDF-Direct] 원문 뒤 200자: {raw[-200:]!r}"
        )
        raise PDFTruncationError(
            f"PDF direct parse JSON 오류: {e}. text extraction fallback으로 전환합니다."
        )

    n_lines = len(result.get("lines") or [])
    print(f"[PDF-Direct] 파싱 완료 — lines={n_lines}, pages={total_pages}")

    # Sanity check: 페이지 수 대비 라인 수가 지나치게 적으면 premature stop 판단 → fallback
    if total_pages >= MIN_PAGES_FOR_LINE_CHECK:
        min_expected = total_pages * MIN_LINES_PER_PAGE
        if n_lines < min_expected:
            print(
                f"[PDF-Direct] 라인 수 부족 ({n_lines}줄 < {total_pages}p × {MIN_LINES_PER_PAGE}) "
                f"— 모델이 일찍 종료된 것으로 판단, text fallback으로 전환"
            )
            raise PDFTruncationError(
                f"PDF direct parse 라인 수 부족 ({n_lines}줄 / {total_pages}페이지). "
                f"text extraction fallback으로 전환합니다."
            )

    alias_map = build_alias_map(result.get("characters") or [])
    result = remap_result(result, alias_map)

    t = time.time()
    result = _enrich_meta(result)
    print(f"[PDF-Direct] enrich_meta: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")
    t = time.time()
    result = _enrich_lines(result)
    print(f"[PDF-Direct] enrich_lines: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")

    _save_cache(cache_key, result)
    print(f"[PDF-Direct] 총 소요시간: {time.time()-t_total:.1f}s")
    return result


def normalize_script_text(text: str) -> str:
    """파싱 전 입력 텍스트 정규화.

    - CRLF / CR → LF
    - 각 줄 trailing whitespace 제거
    - 연속 3개+ 빈 줄 → 빈 줄 1개로 축소
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    # 연속 빈 줄 3개 이상 → 2개(빈 줄 1개)로 축소
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if line == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return "\n".join(result).strip()


def parse_script(script_text: str) -> dict:
    """대본 텍스트를 GPT-4o로 파싱해 구조화된 dict 반환.

    1. MD5 캐시 히트 → 즉시 반환
    2. Fast chunked parse — MAX_WORKERS 병렬 처리
    3. 청크 병합 후 단일 _enrich_meta 호출 (character_analysis + relationships)
    4. 결과 캐시 저장
    """
    t_total = time.time()

    t = time.time()
    script_text = normalize_script_text(script_text)
    total_chars = len(script_text)
    print(f"[Parser] normalize: {time.time()-t:.2f}s ({total_chars}자)")

    # 캐시 확인 — prompt hash prefix로 프롬프트 변경 시 자동 무효화
    cache_key = hashlib.md5(f"{_PROMPT_HASH}:{script_text}".encode()).hexdigest()
    cached = _load_cache(cache_key)
    if cached is not None:
        print(f"[Parser] 캐시 히트: {cache_key[:8]}... ({total_chars}자, prompt={_PROMPT_HASH})")
        return cached

    if total_chars <= CHUNK_THRESHOLD:
        # 짧은 대본: PARSE_FAST_SYSTEM 1회 + _enrich_meta 순차 호출
        # PARSE_SCRIPT_SYSTEM 단일 호출(output ~3,000tok)보다 output token 60% 감소 → 3x 빠름
        print(f"[Parser] 경로: single  | 입력: {total_chars}자")
        t = time.time()
        result = _parse_single(script_text)
        print(f"[Parser] single fast parse: {time.time()-t:.1f}s")
        alias_map = build_alias_map(result.get("characters") or [])
        result = remap_result(result, alias_map)
        t = time.time()
        result = _enrich_meta(result)
        print(f"[Parser] single enrich_meta: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")
        t = time.time()
        result = _enrich_lines(result)
        print(f"[Parser] single enrich_lines: {time.time()-t:.1f}s — lines={len(result.get('lines') or [])}")
        _save_cache(cache_key, result)
        print(f"[Parser] 총 소요시간: {time.time()-t_total:.1f}s")
        return result

    t = time.time()
    chunks = _split_into_chunks(script_text)
    print(
        f"[Parser] chunk split: {time.time()-t:.2f}s | "
        f"{len(chunks)}개 청크 (크기: {[len(c) for c in chunks]})"
    )

    # 청크 처리: 청크 0 선파싱 → 캐릭터 추출 → 나머지 병렬
    t = time.time()
    chunk_results: dict[int, dict] = {}
    failed_chunks: list[int] = []
    recovered_chunks: list[int] = []   # fallback으로 복구된 청크 번호 (1-based)

    def _collect(result: dict | None, chunk_1based: int, chunk_0based: int) -> None:
        """청크 결과를 chunk_results / failed_chunks / recovered_chunks에 분류."""
        if result is None:
            failed_chunks.append(chunk_1based)
        else:
            if result.pop("_recovered_by_fallback", False):
                recovered_chunks.append(chunk_1based)
            chunk_results[chunk_0based] = result

    # Step 1: 청크 0 선파싱 (등장인물 섹션 포함 가능성 높음)
    first_result = _parse_chunk_with_retry(chunks[0], 0, len(chunks))
    _collect(first_result, 1, 0)
    initial_chars = (chunk_results[0].get("characters") or []) if 0 in chunk_results else []
    if initial_chars:
        print(f"[Parser] 초기 캐릭터 추출: {initial_chars}")

    # Step 2: 나머지 청크 병렬 파싱 (캐릭터 컨텍스트 전달)
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
    print(
        f"[Parser] chunk parse 완료 ({time.time()-t:.1f}s) — "
        f"전체 {n_total}청크: 정상 {n_ok}, 복구(fallback) {len(recovered_chunks)}, 실패 {len(failed_chunks)}"
    )

    # 인덱스 순 정렬 후 병합
    results = [chunk_results[i] for i in sorted(chunk_results.keys())]

    if not results:
        raise RuntimeError(f"모든 청크 파싱 실패 ({len(chunks)}개). 유효한 결과가 없습니다.")

    t = time.time()
    try:
        merged = _merge_results(results)
    except Exception as e:
        raise RuntimeError(f"청크 병합 실패: {e}") from e
    print(f"[Parser] merge: {time.time()-t:.2f}s")

    # 청크 병합 후 전체 canonical remap
    alias_map = build_alias_map(merged.get("characters") or [])
    merged = remap_result(merged, alias_map)

    if failed_chunks or recovered_chunks:
        merged["partial_failure"] = {
            "failed_chunks": failed_chunks,
            "recovered_chunks": recovered_chunks,
            "total_chunks": len(chunks),
        }
        if failed_chunks:
            print(f"[Parser] 부분 실패: {len(failed_chunks)}/{len(chunks)} 청크 실패 (청크: {failed_chunks})")
        if recovered_chunks:
            print(f"[Parser] fallback 복구: {len(recovered_chunks)}개 청크 복구 성공 (청크: {recovered_chunks})")

    print(
        f"[Parser] 병합 완료 - 캐릭터 {len(merged['characters'])}명, "
        f"대사 {len(merged['lines'])}줄"
    )

    # 단일 meta enrich (character_analysis + relationships)
    t = time.time()
    merged = _enrich_meta(merged)
    print(f"[Parser] enrich_meta: {time.time()-t:.1f}s — lines={len(merged.get('lines') or [])}")
    t = time.time()
    merged = _enrich_lines(merged)
    print(f"[Parser] enrich_lines: {time.time()-t:.1f}s — lines={len(merged.get('lines') or [])}")

    _save_cache(cache_key, merged)
    print(f"[Parser] 총 소요시간: {time.time()-t_total:.1f}s")
    return merged


# ── 내부 헬퍼 ──────────────────────────────────────────────

def _classify_json_failure(raw: str, input_len: int, finish_reason: str, e: json.JSONDecodeError) -> str:
    """JSON 파싱 실패 원인을 분류하고 진단 로그를 출력한다.

    분류 레이블:
      truncation        — finish_reason='length' → 출력 토큰 한도 초과로 잘림
      unterminated_str  — JSONDecodeError 메시지에 'unterminated string' 포함
      fence_leaked      — ``` fence 마커가 raw에 남아있음
      commentary_prefix — raw가 { 이외 문자로 시작 (설명문 혼입)
      no_closing_brace  — raw에 } 없음 (완전한 JSON 객체 미완성)
      empty_response    — raw가 비어있음
      malformed_json    — 위 분류에 해당하지 않는 일반 파싱 오류
    """
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

    print(
        f"[Parser] JSON 실패 분류: [{label}]\n"
        f"  finish_reason  : {finish_reason!r}\n"
        f"  input_length   : {input_len}자\n"
        f"  raw_length     : {len(raw)}자\n"
        f"  has_fence      : {has_fence}\n"
        f"  has_closing_}}  : {has_closing_brace}\n"
        f"  raw_head       : {raw[:120]!r}\n"
        f"  raw_tail       : {raw[-80:]!r}\n"
        f"  json_error     : {e}"
    )
    return label


def _parse_single(text: str, known_characters: list[str] | None = None) -> dict:
    """단일 텍스트를 GPT-4o 1회 호출로 구조적 파싱 (actor analysis 없음).

    known_characters: 앞 청크에서 추출한 캐릭터 이름 목록.
      전달 시 "이 이름들로 시작하는 줄을 dialogue로 처리하세요" 지시를 user 메시지 앞에 추가.
      한국어 '화자명 + 공백 + 대사' 형식 대본에서 후속 청크 오분류 방지.
    finish_reason='length': 출력 토큰 한도 초과 → JSON 잘림 → JSONDecodeError 가능성 높음.
    JSON 파싱 실패 시 _classify_json_failure()로 원인을 분류하고 exception에 attach해서 re-raise.
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
        print(
            f"[Parser] WARN finish_reason='{finish_reason}' "
            f"(입력 {len(text)}자) - JSON이 중간에 잘렸을 수 있음"
        )

    # PDF direct path와 동일한 safe preprocessing (fence 제거 + 선행 텍스트 제거)
    raw_original_len = len(raw)
    raw = _strip_json_fences(raw)
    if len(raw) != raw_original_len:
        print(f"[Parser] preprocessing: {raw_original_len}자 → {len(raw)}자 (fence/선행텍스트 제거)")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        label = _classify_json_failure(raw, len(text), finish_reason, e)
        e.classification = label  # type: ignore[attr-defined]
        raise



def _split_chunk_in_half(text: str) -> tuple[str, str]:
    """청크를 중간점에서 가장 가까운 빈 줄 경계로 2분할.

    빈 줄 없으면 단순 줄 경계, 그것도 없으면 단순 글자 중간점으로 fallback.
    """
    mid = len(text) // 2
    split_pos = text.rfind('\n\n', 0, mid)
    if split_pos == -1:
        split_pos = text.rfind('\n', 0, mid)
    if split_pos == -1:
        split_pos = mid
    return text[:split_pos].strip(), text[split_pos:].strip()


def _parse_chunk_json_fallback(chunk: str, idx: int, total: int, known_characters: list[str] | None) -> dict | None:
    """JSON 오류 청크를 FALLBACK_CHUNK_SIZE로 재분할해 재시도. 성공분만 병합해 반환.

    정상 경로는 CHUNK_SIZE(4000자) 사용. 이 경로는 JSON 오류 시에만 호출된다.
    분할은 1회로 제한 (재귀 없음).
    """
    subchunks = _split_into_chunks(chunk, max_chars=FALLBACK_CHUNK_SIZE)
    print(
        f"[Parser] 청크 {idx+1}/{total} fallback 재분할: "
        f"{len(chunk)}자(원본 {CHUNK_SIZE}자 기준) → {len(subchunks)}개({FALLBACK_CHUNK_SIZE}자 기준)"
    )
    results = []
    n_sub = len(subchunks)
    for part_num, part in enumerate(subchunks, 1):
        if not part:
            continue
        try:
            res = _parse_single(part, known_characters=known_characters)
            n = len(res.get("lines") or [])
            print(f"[Parser] 청크 {idx+1}/{total} subchunk {part_num}/{n_sub} 성공 — lines={n}")
            results.append(res)
        except Exception as sub_e:
            label = getattr(sub_e, "classification", "")
            suffix = f" [{label}]" if label else ""
            print(f"[Parser] 청크 {idx+1}/{total} subchunk {part_num}/{n_sub} 실패{suffix}: {sub_e}")

    if not results:
        print(f"[Parser] 청크 {idx+1}/{total} subchunk 모두 실패 → 폐기")
        return None

    out = results[0] if len(results) == 1 else _merge_results(results)
    n = len(out.get("lines") or [])
    print(f"[Parser] 청크 {idx+1}/{total} subchunk {len(results)}/{n_sub}개 복구 완료 — lines={n}")
    out["_recovered_by_fallback"] = True  # parse_script()에서 recovered_chunks 집계용 sentinel
    return out


def _parse_chunk_with_retry(chunk: str, idx: int, total: int, known_characters: list[str] | None = None) -> dict | None:
    """단일 청크를 파싱한다. 실패 시 1회 재시도. None 반환 시 실패.

    known_characters: 앞 청크에서 추출한 캐릭터 이름. _parse_single()로 전달.
    JSONDecodeError: 같은 입력 재시도 대신 2분할 subchunk fallback 1회 시도.
    """
    t = time.time()
    for attempt in range(2):
        try:
            result = _parse_single(chunk, known_characters=known_characters)
            n_lines = len(result.get("lines") or [])
            n_chars = len(result.get("characters") or [])
            print(f"[Parser] 청크 {idx+1}/{total} 완료 ({time.time()-t:.1f}s) — lines={n_lines}, chars={n_chars}")
            return result
        except json.JSONDecodeError as e:
            label = getattr(e, "classification", "unknown")
            print(f"[Parser] 청크 {idx+1}/{total} JSON 오류 [{label}] → subchunk 분할 재시도")
            return _parse_chunk_json_fallback(chunk, idx, total, known_characters)
        except Exception as e:
            if attempt == 0:
                print(f"[Parser] 청크 {idx+1}/{total} 실패 (재시도 중): {e}")
            else:
                print(f"[Parser] 청크 {idx+1}/{total} 최종 실패: {e}")
    return None


def _enrich_meta(merged: dict) -> dict:
    """병합 결과에 character_analysis + relationships를 단일 API 호출로 추가.

    실패 시 빈 dict로 fallback — 리허설 흐름은 character_analysis 없이도 동작.
    캐스트가 많을수록 relationships 쌍이 폭발적으로 늘어나므로,
    대사 빈도 기준 상위 MAX_ENRICH_CHARS명으로 제한한다.
    """
    # 4명: directed pairs 12쌍 → ~1,780 tokens (8명은 56쌍 → ~4,000 tokens → slow)
    MAX_ENRICH_CHARS = 4

    chars = merged.get("characters") or []
    if not chars:
        merged.setdefault("character_analysis", {})
        merged.setdefault("relationships", {})
        return merged

    # 대사 빈도 기준 상위 N명으로 제한
    if len(chars) > MAX_ENRICH_CHARS:
        line_counts: dict[str, int] = {}
        for line in merged.get("lines") or []:
            c = line.get("character")
            if c:
                line_counts[c] = line_counts.get(c, 0) + 1
        chars = sorted(chars, key=lambda c: line_counts.get(c, 0), reverse=True)[:MAX_ENRICH_CHARS]
        print(f"[Parser] Meta enrich: 캐스트 많음 → 상위 {MAX_ENRICH_CHARS}명만 분석")

    descs = merged.get("character_descriptions") or {}
    chars_info = "\n".join(
        f"- {c}: {descs.get(c, '설명 없음')}" for c in chars
    )
    prompt = f"캐릭터 목록:\n{chars_info}"

    # 캐릭터 수에 비례한 max_tokens 산정: character_analysis(~135 tok/명) + relationships(~95 tok/쌍)
    # directed pairs = n*(n-1) → 4명: 12쌍 → ~1,780 tokens; 2명: 2쌍 → ~780 tokens
    max_enrich_tokens = min(3_000, max(1_200, len(chars) * 700))

    try:
        response = client.chat.completions.create(
            model=OPENAI_ENRICH_MODEL,
            messages=[
                {"role": "system", "content": ENRICH_META_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.3,
            max_tokens=max_enrich_tokens,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        enrich = json.loads(raw)
        merged["character_analysis"] = enrich.get("character_analysis") or {}
        merged["relationships"] = enrich.get("relationships") or {}
        print(f"[Parser] Meta enrich 완료 - 캐릭터 {len(chars)}명 (max_tokens={max_enrich_tokens})")
    except Exception as e:
        print(f"[Parser] Meta enrich 실패 (fallback 빈 dict): {e}")
        merged.setdefault("character_analysis", {})
        merged.setdefault("relationships", {})

    return merged


def _enrich_lines(merged: dict) -> dict:
    """대화 라인에 beat_goal, subtext, tts_direction을 배치 병렬로 추가.

    character_analysis + relationships + 라인 배치를 입력으로 받아
    per-line 퍼포먼스 데이터를 생성하고 원본 lines에 병합한다.
    실패한 배치는 건너뜀 — 리허설 범위는 항상 유지.
    """
    lines = merged.get("lines") or []
    char_analysis = merged.get("character_analysis") or {}
    relationships = merged.get("relationships") or {}

    # dialogue 라인 인덱스만 추출
    dialogue_indices = [i for i, line in enumerate(lines) if line.get("type") == "dialogue"]
    if not dialogue_indices:
        return merged

    # character_analysis + relationships 컨텍스트 (배치마다 공유)
    context = json.dumps(
        {"character_analysis": char_analysis, "relationships": relationships},
        ensure_ascii=False,
    )

    # 배치 분할
    batches = [
        dialogue_indices[i: i + ENRICH_LINES_BATCH_SIZE]
        for i in range(0, len(dialogue_indices), ENRICH_LINES_BATCH_SIZE)
    ]

    def enrich_batch(batch_indices: list[int]) -> dict[int, dict]:
        batch_lines = [
            {
                "idx": i,
                "char": lines[i].get("character"),
                "text": lines[i].get("text"),
                "emotion_label": lines[i].get("emotion_label"),
                "intensity": lines[i].get("intensity", 2),
            }
            for i in batch_indices
        ]
        user_content = context + "\n\nLines:\n" + json.dumps(batch_lines, ensure_ascii=False)
        try:
            response = client.chat.completions.create(
                model=OPENAI_ENRICH_MODEL,
                messages=[
                    {"role": "system", "content": ENRICH_LINES_SYSTEM},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.3,
                max_tokens=ENRICH_LINES_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            result = json.loads(raw)
            return {int(k): v for k, v in (result.get("results") or {}).items()}
        except Exception as e:
            print(f"[Parser] enrich_lines 배치 실패 (fallback): {e}")
            return {}

    t = time.time()
    all_results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(enrich_batch, batch): batch for batch in batches}
        for future in as_completed(futures):
            all_results.update(future.result())

    # 결과를 원본 lines에 병합 (기존 값 덮어쓰지 않음)
    enriched = 0
    for idx, perf in all_results.items():
        if idx < len(lines):
            for field in ("beat_goal", "subtext", "tts_direction"):
                val = perf.get(field)
                if val and not lines[idx].get(field):
                    lines[idx][field] = val
            enriched += 1

    merged["lines"] = lines
    n_batches = len(batches)
    print(
        f"[Parser] enrich_lines: {time.time()-t:.1f}s — "
        f"{enriched}/{len(dialogue_indices)}줄 enriched ({n_batches}배치)"
    )
    return merged


def _strip_json_fences(raw: str) -> str:
    """LLM 응답에서 markdown JSON fence와 선행 텍스트를 제거한다.

    - ```json ... ``` 또는 ``` ... ``` 형태 제거
    - { 이전에 붙은 비-JSON 주석 제거
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```\s*$', '', raw)
        raw = raw.strip()
    idx = raw.find('{')
    if idx > 0:
        raw = raw[idx:]
    return raw


def _load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _split_into_chunks(text: str, max_chars: int = CHUNK_SIZE) -> list[str]:
    """빈 줄 경계 단위로 텍스트를 청크로 분할한다.

    한국어 대본의 대사 블록은 빈 줄로 구분되므로,
    빈 줄 기준으로 자르면 대사가 중간에 잘리지 않는다.
    """
    blocks = re.split(r'\n\n+', text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        block_len = len(block)
        if current_len + block_len + 2 > max_chars and current:
            chunks.append('\n\n'.join(current))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += block_len + 2

    if current:
        chunks.append('\n\n'.join(current))

    return chunks or [text]


def canonicalize_character_name(name: str) -> str:
    """Character 이름에서 노이즈를 제거하고 canonical form을 반환.

    처리 규칙:
    - 앞뒤 공백 / 연속 whitespace 정리
    - 앞에 붙은 '번 ' 노이즈 제거: '번 배심원8' → '배심원8'
    """
    name = re.sub(r'\s+', ' ', name.strip())
    # '번 배심원8' 같은 앞 '번 ' 노이즈 제거
    name = re.sub(r'^번\s+', '', name)
    return name


def build_alias_map(characters: list[str]) -> dict[str, str]:
    """character 이름 목록에서 canonical form 기준 alias map을 생성.

    반환: {원래이름: canonical이름}
    같은 canonical form을 가진 이름 중 '더 긴 것'을 canonical로 선택.
    (노이즈 제거 후 동일하면 먼저 등장한 이름 우선)
    """
    canonical_to_first: dict[str, str] = {}
    alias_map: dict[str, str] = {}
    for name in characters:
        canon = canonicalize_character_name(name)
        if canon not in canonical_to_first:
            canonical_to_first[canon] = name
        alias_map[name] = canonical_to_first[canon]
    return alias_map


def remap_result(result: dict, alias_map: dict[str, str]) -> dict:
    """parse 결과 전체에 alias_map을 적용해 canonical name으로 통일.

    적용 대상: characters, character_descriptions, character_analysis,
               relationships, lines[].character
    """
    def canon(name: str) -> str:
        return alias_map.get(name, canonicalize_character_name(name))

    result["characters"] = list(dict.fromkeys(
        canon(c) for c in result.get("characters") or []
    ))

    result["character_descriptions"] = {
        canon(k): v
        for k, v in (result.get("character_descriptions") or {}).items()
    }

    result["character_analysis"] = {
        canon(k): v
        for k, v in (result.get("character_analysis") or {}).items()
    }

    new_rel: dict = {}
    for key, val in (result.get("relationships") or {}).items():
        if " -> " in key:
            a, b = key.split(" -> ", 1)
            new_key = f"{canon(a)} -> {canon(b)}"
        else:
            new_key = key
        if new_key not in new_rel:
            new_rel[new_key] = val
    result["relationships"] = new_rel

    for line in result.get("lines") or []:
        if line.get("character"):
            line["character"] = canon(line["character"])

    return result


def _merge_results(results: list[dict]) -> dict:
    """여러 청크 파싱 결과를 하나의 dict로 병합한다.

    title:                  첫 번째로 등장하는 유효한 제목 사용
    characters:             등장 순서 유지 + strip 기준 중복 제거
    character_descriptions: 처음 등장한 설명 유지 (첫 청크가 더 완전한 소개를 포함)
    lines:                  청크 순서대로 그대로 연결 (순서 보장됨)
    """
    # title: 첫 번째 "제목 없음" 아닌 값
    title = "제목 없음"
    for r in results:
        t = (r.get("title") or "").strip()
        if t and t != "제목 없음":
            title = t
            break

    # characters: 순서 있는 합집합 (2자 미만 단편 제거)
    seen: set[str] = set()
    characters: list[str] = []
    for r in results:
        for c in r.get("characters") or []:
            c_norm = c.strip()
            if c_norm and len(c_norm) >= 2 and c_norm not in seen:
                seen.add(c_norm)
                characters.append(c_norm)

    # character_descriptions: 처음 등장한 설명 우선
    descriptions: dict[str, str] = {}
    for r in results:
        for char, desc in (r.get("character_descriptions") or {}).items():
            char_norm = char.strip()
            if char_norm not in descriptions and desc:
                descriptions[char_norm] = desc

    # character_analysis: 처음 등장한 분석 우선 (superobjective 등)
    char_analysis: dict[str, dict] = {}
    for r in results:
        for char, analysis in (r.get("character_analysis") or {}).items():
            char_norm = char.strip()
            if char_norm not in char_analysis and analysis:
                char_analysis[char_norm] = analysis

    # relationships: 처음 등장한 관계 우선
    relationships: dict[str, dict] = {}
    for r in results:
        for key, val in (r.get("relationships") or {}).items():
            if key not in relationships and val:
                relationships[key] = val

    # lines: 순서대로 concat + character strip 정규화
    all_lines: list[dict] = []
    for r in results:
        for line in r.get("lines") or []:
            if line.get("character"):
                line["character"] = line["character"].strip()
            all_lines.append(line)

    return {
        "title": title,
        "characters": characters,
        "character_descriptions": descriptions,
        "character_analysis": char_analysis,
        "relationships": relationships,
        "lines": all_lines,
    }
