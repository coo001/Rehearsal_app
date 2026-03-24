"""GPT-4o 대본 파싱 서비스."""

import hashlib
import json
import re
from pathlib import Path

from app.core.config import client
from app.prompts.templates import ENRICH_META_SYSTEM, PARSE_FAST_SYSTEM

# 단일 청크 최대 길이
CHUNK_SIZE = 3_000

# 이 길이 이하는 단일 호출 사용 (청크 오버헤드 불필요)
CHUNK_THRESHOLD = 3_500

# fast parse용 output token 상한 — actor fields 없으므로 4096으로 충분
MAX_TOKENS = 4_096

# 파싱 결과 캐시 디렉토리
CACHE_DIR = Path("data/parse_cache")


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
    2. Fast chunked parse (actor fields 없음)
    3. 청크 병합 후 단일 _enrich_meta 호출 (character_analysis + relationships)
    4. 결과 캐시 저장
    """
    script_text = normalize_script_text(script_text)
    total_chars = len(script_text)

    # 캐시 확인
    cache_key = hashlib.md5(script_text.encode()).hexdigest()
    cached = _load_cache(cache_key)
    if cached is not None:
        print(f"[Parser] 캐시 히트: {cache_key[:8]}... ({total_chars}자)")
        return cached

    if total_chars <= CHUNK_THRESHOLD:
        print(f"[Parser] 경로: single  | 입력: {total_chars}자")
        result = _parse_single(script_text)
        alias_map = build_alias_map(result.get("characters") or [])
        result = remap_result(result, alias_map)
        result = _enrich_meta(result)
        _save_cache(cache_key, result)
        return result

    chunks = _split_into_chunks(script_text)
    chunk_sizes = [len(c) for c in chunks]
    print(
        f"[Parser] 경로: chunked | 입력: {total_chars}자 => "
        f"{len(chunks)}개 청크 크기: {chunk_sizes}"
    )

    results: list[dict] = []
    failed_chunks: list[int] = []
    for i, chunk in enumerate(chunks):
        print(f"[Parser] 청크 {i + 1}/{len(chunks)} 파싱 중 ({len(chunk)}자)...")
        chunk_result = None
        for attempt in range(2):  # 최대 1회 재시도
            try:
                chunk_result = _parse_single(chunk)
                break
            except Exception as e:
                if attempt == 0:
                    print(f"[Parser] 청크 {i + 1}/{len(chunks)} 실패 (재시도 중): {e}")
                else:
                    print(f"[Parser] 청크 {i + 1}/{len(chunks)} 최종 실패: {e}")
                    failed_chunks.append(i + 1)
        if chunk_result is not None:
            results.append(chunk_result)
            print(f"[Parser] 청크 {i + 1}/{len(chunks)} 완료")

    if not results:
        raise RuntimeError(f"모든 청크 파싱 실패 ({len(chunks)}개). 유효한 결과가 없습니다.")

    try:
        merged = _merge_results(results)
    except Exception as e:
        raise RuntimeError(f"청크 병합 실패: {e}") from e

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
    merged = _enrich_meta(merged)
    _save_cache(cache_key, merged)
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


def _enrich_meta(merged: dict) -> dict:
    """병합 결과에 character_analysis + relationships를 단일 API 호출로 추가.

    실패 시 빈 dict로 fallback — 리허설 흐름은 character_analysis 없이도 동작.
    """
    chars = merged.get("characters") or []
    if not chars:
        merged.setdefault("character_analysis", {})
        merged.setdefault("relationships", {})
        return merged

    descs = merged.get("character_descriptions") or {}
    chars_info = "\n".join(
        f"- {c}: {descs.get(c, '설명 없음')}" for c in chars
    )
    prompt = f"캐릭터 목록:\n{chars_info}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": ENRICH_META_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4_096,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        enrich = json.loads(raw)
        merged["character_analysis"] = enrich.get("character_analysis") or {}
        merged["relationships"] = enrich.get("relationships") or {}
        print(f"[Parser] Meta enrich 완료 - 캐릭터 {len(chars)}명")
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
