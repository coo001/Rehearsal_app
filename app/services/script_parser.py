"""GPT-4o 대본 파싱 서비스."""

import json
import re

from app.core.config import client
from app.prompts.templates import PARSE_SCRIPT_SYSTEM

# 단일 청크 최대 길이.
# gpt-4o 출력 한도(4,096 tokens) 기준: 5,000자 ≈ 40~50대사 → 출력 ~2,200 tokens → 안전.
CHUNK_SIZE = 5_000

# 이 길이 이하는 단일 호출 사용 (청크 오버헤드 불필요)
CHUNK_THRESHOLD = 5_500


def parse_script(script_text: str) -> dict:
    """대본 텍스트를 GPT-4o로 파싱해 구조화된 dict 반환.

    CHUNK_THRESHOLD 이하 → 단일 호출.
    초과 → 청크 분할 후 병합.
    JSONDecodeError 또는 API 예외는 호출자(route)가 처리한다.
    """
    total_chars = len(script_text)

    if total_chars <= CHUNK_THRESHOLD:
        print(f"[Parser] 경로: single  | 입력: {total_chars}자")
        return _parse_single(script_text)

    chunks = _split_into_chunks(script_text)
    chunk_sizes = [len(c) for c in chunks]
    print(
        f"[Parser] 경로: chunked | 입력: {total_chars}자 => "
        f"{len(chunks)}개 청크 크기: {chunk_sizes}"
    )

    results: list[dict] = []
    for i, chunk in enumerate(chunks):
        print(f"[Parser] 청크 {i + 1}/{len(chunks)} 파싱 중 ({len(chunk)}자)...")
        try:
            results.append(_parse_single(chunk))
            print(f"[Parser] 청크 {i + 1}/{len(chunks)} 완료")
        except Exception as e:
            raise RuntimeError(f"청크 {i + 1}/{len(chunks)} 파싱 실패: {e}") from e

    try:
        merged = _merge_results(results)
    except Exception as e:
        raise RuntimeError(f"청크 병합 실패: {e}") from e

    print(
        f"[Parser] 병합 완료 - 캐릭터 {len(merged['characters'])}명, "
        f"대사 {len(merged['lines'])}줄"
    )
    return merged


# ── 내부 헬퍼 ──────────────────────────────────────────────

def _parse_single(text: str) -> dict:
    """단일 텍스트를 GPT-4o 1회 호출로 파싱.

    finish_reason='length': 출력 토큰 한도 초과 → JSON 잘림 → JSONDecodeError 가능성 높음.
    JSON 파싱 실패 시 LLM 원문 앞 300자를 로그에 남겨 원인 파악을 돕는다.
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": PARSE_SCRIPT_SYSTEM},
            {"role": "user",   "content": f"다음 대본을 분석해주세요:\n\n{text}"},
        ],
        temperature=0.3,
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

    # characters: 순서 있는 합집합
    seen: set[str] = set()
    characters: list[str] = []
    for r in results:
        for c in r.get("characters") or []:
            c_norm = c.strip()
            if c_norm and c_norm not in seen:
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
        "lines": all_lines,
    }
