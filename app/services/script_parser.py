"""GPT-4o 대본 파싱 서비스."""

import base64
import hashlib
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.core.config import client
from app.prompts.templates import ENRICH_META_SYSTEM, PARSE_FAST_SYSTEM, PARSE_SCRIPT_SYSTEM  # PARSE_SCRIPT_SYSTEM: PDF direct path에서 사용

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

# 파싱 결과 캐시 디렉토리
CACHE_DIR = Path("data/parse_cache")


def parse_script_pdf(pdf_bytes: bytes, filename: str = "script.pdf", total_pages: int = 0) -> dict:
    """PDF를 base64 인라인으로 Responses API에 직접 전달해 파싱한다.

    chat.completions는 file content type을 지원하지 않으므로
    Responses API(client.responses.create)로 base64 인라인 전달.
    Files API 업로드/삭제 없이 PDF 바이트를 직접 모델에 전달한다.
    """
    t_total = time.time()
    cache_key = hashlib.md5(pdf_bytes).hexdigest()
    cached = _load_cache(cache_key)
    if cached is not None:
        print(f"[PDF-Direct] 캐시 히트: {cache_key[:8]}... ({total_pages}페이지)")
        return cached

    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    print(f"[PDF-Direct] Responses API 호출 중... ({len(pdf_bytes):,}B, {total_pages}페이지)")
    t = time.time()
    response = client.responses.create(
        model="gpt-4o",
        instructions=PARSE_SCRIPT_SYSTEM,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": filename,
                        "file_data": f"data:application/pdf;base64,{pdf_b64}",
                    },
                    {"type": "input_text", "text": "이 대본을 분석해주세요."},
                ],
            }
        ],
        text={"format": {"type": "json_object"}},
        temperature=0.3,
        max_output_tokens=8_192,
    )
    print(f"[PDF-Direct] 완료 ({time.time()-t:.1f}s)")

    raw = response.output_text or "{}"
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[PDF-Direct] JSONDecodeError — 응답 앞 300자: {raw[:300]!r}")
        raise

    alias_map = build_alias_map(result.get("characters") or [])
    result = remap_result(result, alias_map)
    result.setdefault("character_analysis", {})
    result.setdefault("relationships", {})
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

    # 캐시 확인
    cache_key = hashlib.md5(script_text.encode()).hexdigest()
    cached = _load_cache(cache_key)
    if cached is not None:
        print(f"[Parser] 캐시 히트: {cache_key[:8]}... ({total_chars}자)")
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
        print(f"[Parser] single enrich_meta: {time.time()-t:.1f}s")
        _save_cache(cache_key, result)
        print(f"[Parser] 총 소요시간: {time.time()-t_total:.1f}s")
        return result

    t = time.time()
    chunks = _split_into_chunks(script_text)
    print(
        f"[Parser] chunk split: {time.time()-t:.2f}s | "
        f"{len(chunks)}개 청크 (크기: {[len(c) for c in chunks]})"
    )

    # 병렬 청크 처리
    t = time.time()
    chunk_results: dict[int, dict] = {}
    failed_chunks: list[int] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(_parse_chunk_with_retry, chunk, i, len(chunks)): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            result = future.result()  # _parse_chunk_with_retry는 None 또는 dict 반환
            if result is not None:
                chunk_results[i] = result
            else:
                failed_chunks.append(i + 1)

    print(f"[Parser] chunk parse (병렬 {MAX_WORKERS}workers): {time.time()-t:.1f}s")

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

    if failed_chunks:
        merged["partial_failure"] = {
            "failed_chunks": failed_chunks,
            "total_chunks": len(chunks),
        }
        print(
            f"[Parser] 부분 실패: {len(failed_chunks)}/{len(chunks)} 청크 실패 "
            f"(실패 청크: {failed_chunks})"
        )

    print(
        f"[Parser] 병합 완료 - 캐릭터 {len(merged['characters'])}명, "
        f"대사 {len(merged['lines'])}줄"
    )

    # 단일 meta enrich (character_analysis + relationships)
    t = time.time()
    merged = _enrich_meta(merged)
    print(f"[Parser] enrich_meta: {time.time()-t:.1f}s")

    _save_cache(cache_key, merged)
    print(f"[Parser] 총 소요시간: {time.time()-t_total:.1f}s")
    return merged


# ── 내부 헬퍼 ──────────────────────────────────────────────

def _parse_single(text: str) -> dict:
    """단일 텍스트를 GPT-4o 1회 호출로 구조적 파싱 (actor analysis 없음).

    finish_reason='length': 출력 토큰 한도 초과 → JSON 잘림 → JSONDecodeError 가능성 높음.
    JSON 파싱 실패 시 LLM 원문 앞 300자를 로그에 남겨 원인 파악을 돕는다.
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": PARSE_FAST_SYSTEM},
            {"role": "user",   "content": f"다음 대본을 분석해주세요:\n\n{text}"},
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

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(
            f"[Parser] JSONDecodeError - finish_reason='{finish_reason}', "
            f"입력 {len(text)}자\n"
            f"[Parser]    LLM 응답 원문 (앞 300자): {raw[:300]!r}"
        )
        raise



def _parse_chunk_with_retry(chunk: str, idx: int, total: int) -> dict | None:
    """단일 청크를 파싱한다. 실패 시 1회 재시도. None 반환 시 실패.

    JSONDecodeError는 같은 입력으로 재시도해도 동일한 결과 → 재시도 없이 즉시 실패.
    """
    t = time.time()
    for attempt in range(2):
        try:
            result = _parse_single(chunk)
            print(f"[Parser] 청크 {idx+1}/{total} 완료 ({time.time()-t:.1f}s)")
            return result
        except json.JSONDecodeError as e:
            print(f"[Parser] 청크 {idx+1}/{total} JSON 오류 (재시도 없음): {e}")
            return None
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
            model="gpt-4o",
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
