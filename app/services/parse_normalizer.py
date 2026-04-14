"""대본 텍스트·캐릭터 이름 정규화 및 청크 분할.

순수 함수만 포함 — 외부 API 호출 없음.
"""

import re

# _split_into_chunks 기본 청크 크기 (script_parser.py 의 CHUNK_SIZE 와 일치)
CHUNK_SIZE = 4_000


# ── 텍스트 정규화 ────────────────────────────────────────────────

def normalize_script_text(text: str) -> str:
    """파싱 전 입력 텍스트 정규화.

    - CRLF / CR → LF
    - 각 줄 trailing whitespace 제거
    - 연속 3개+ 빈 줄 → 빈 줄 1개로 축소
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
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


def _strip_json_fences(raw: str) -> str:
    """LLM 응답에서 markdown JSON fence와 선행/후행 비-JSON 텍스트를 제거한다.

    - ```json ... ``` 또는 ``` ... ``` 형태 제거 (선행 텍스트 있어도 처리)
    - { 이전에 붙은 비-JSON 주석 제거
    - 마지막 } 이후 후행 텍스트 제거
    """
    raw = raw.strip()
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()
    idx = raw.find('{')
    if idx > 0:
        raw = raw[idx:]
    last = raw.rfind('}')
    if 0 <= last < len(raw) - 1:
        raw = raw[:last + 1]
    return raw.strip()


# ── 청크 분할 ────────────────────────────────────────────────────

def _split_into_chunks(text: str, max_chars: int = CHUNK_SIZE) -> list[str]:
    """빈 줄 경계 단위로 텍스트를 청크로 분할한다.

    한국어 대본의 대사 블록은 빈 줄로 구분되므로,
    빈 줄 기준으로 자르면 대사가 중간에 잘리지 않는다.

    PDF 추출 텍스트처럼 \\n\\n이 없는 경우 단일 블록이 max_chars를 초과할 수 있다.
    이 경우 \\n 단위로 재분할해 청크 크기를 보장한다.
    """
    blocks = re.split(r'\n\n+', text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        block_len = len(block)

        if block_len > max_chars:
            if current:
                chunks.append('\n\n'.join(current))
                current, current_len = [], 0
            sub_buf: list[str] = []
            sub_len = 0
            for line in block.split('\n'):
                line_len = len(line)
                if sub_len + line_len + 1 > max_chars and sub_buf:
                    chunks.append('\n'.join(sub_buf))
                    sub_buf, sub_len = [line], line_len
                else:
                    sub_buf.append(line)
                    sub_len += line_len + 1
            if sub_buf:
                chunks.append('\n'.join(sub_buf))
            continue

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


# ── 캐릭터 이름 정규화 ────────────────────────────────────────────

def canonicalize_character_name(name: str) -> str:
    """Character 이름에서 노이즈를 제거하고 canonical form을 반환.

    처리 규칙:
    - 앞뒤 공백 / 연속 whitespace 정리
    - 앞에 붙은 '번 ' 노이즈 제거: '번 배심원8' → '배심원8'
    """
    name = re.sub(r'\s+', ' ', name.strip())
    name = re.sub(r'^번\s+', '', name)
    return name


def build_alias_map(characters: list[str]) -> dict[str, str]:
    """character 이름 목록에서 canonical form 기준 alias map을 생성.

    반환: {원래이름: canonical이름}
    같은 canonical form을 가진 이름 중 먼저 등장한 이름을 canonical로 선택.
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


# ── 청크 결과 병합 ────────────────────────────────────────────────

def merge_results(results: list[dict]) -> dict:
    """여러 청크 파싱 결과를 하나의 dict로 병합한다.

    title:                  첫 번째로 등장하는 유효한 제목 사용
    characters:             등장 순서 유지 + strip 기준 중복 제거
    character_descriptions: 처음 등장한 설명 유지 (첫 청크가 더 완전한 소개를 포함)
    lines:                  청크 순서대로 그대로 연결 (순서 보장됨)
    """
    title = "제목 없음"
    for r in results:
        t = (r.get("title") or "").strip()
        if t and t != "제목 없음":
            title = t
            break

    seen: set[str] = set()
    characters: list[str] = []
    for r in results:
        for c in r.get("characters") or []:
            c_norm = c.strip()
            if c_norm and len(c_norm) >= 2 and c_norm not in seen:
                seen.add(c_norm)
                characters.append(c_norm)

    descriptions: dict[str, str] = {}
    for r in results:
        for char, desc in (r.get("character_descriptions") or {}).items():
            char_norm = char.strip()
            if char_norm not in descriptions and desc:
                descriptions[char_norm] = desc

    char_analysis: dict[str, dict] = {}
    for r in results:
        for char, analysis in (r.get("character_analysis") or {}).items():
            char_norm = char.strip()
            if char_norm not in char_analysis and analysis:
                char_analysis[char_norm] = analysis

    relationships: dict[str, dict] = {}
    for r in results:
        for key, val in (r.get("relationships") or {}).items():
            if key not in relationships and val:
                relationships[key] = val

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
