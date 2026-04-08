"""구조화된 line analysis를 provider-ready TTS instruction string으로 조립한다.

조립 우선순위:
  1. speech_act   → 발화 행동 프레임 (sentence 1 앞부분)
  2. delivery_mode → 전달 질감 (sentence 1 뒷부분 또는 sentence 1 전체)
  3. ending_shape  → 끝처리 (sentence 2 앞부분)
  4. phrase_breaks → 내부 끊김 (sentence 2 뒷부분)
  5. subtext       → speech_act/delivery_mode 없을 때 내적 앵커로 sentence 1
  6. tts_direction → 최후 fallback (sentence 1)

사용 예:
  instruction = build_tts_instruction(line)
  # → "상대를 떠보듯 낮게 시작한다. 끝을 닫아 말한다. 중간에 짧게 멈춘다."
"""

_ENDING_MAP: dict[str, str] = {
    "삼킴": "말끝을 삼키듯 끊는다",
    "눌림": "말끝을 내리눌러 닫는다",
    "올라감": "말끝을 약하게 올린다",
    "닫힘": "끝을 닫아 말한다",
    "흘러나감": "말끝을 약하게 흘린다",
    "열림": "말끝을 열어둔다",
}


def build_tts_instruction(
    line: dict,
    character_analysis: dict | None = None,
    relationship_context: dict | None = None,
) -> str:
    """구조화된 line analysis를 짧고 명확한 TTS instruction string으로 반환한다.

    Args:
        line: PARSE_SCRIPT / ENRICH_LINES 출력의 dialogue line dict.
        character_analysis: 화자의 character_analysis 항목 (optional, 향후 확장용).
        relationship_context: 관련 관계 항목 (optional, 향후 확장용).

    Returns:
        Korean instruction string (≤2 문장). 사용 가능한 필드 없으면 빈 문자열.
    """
    act      = _str(line, "speech_act")
    mode     = _str(line, "delivery_mode")
    ending   = _str(line, "ending_shape")
    breaks   = _str(line, "phrase_breaks")
    subtext  = _str(line, "subtext")
    fallback = _str(line, "tts_direction")

    s1 = _sentence1(act, mode, subtext)
    s2 = _sentence2(ending, breaks)

    result = " ".join(filter(None, [s1, s2])).strip()
    return result if result else fallback


# ─── private helpers ──────────────────────────────────────────────────────────

def _str(line: dict, key: str) -> str:
    """None 방지 — 항상 stripped string 반환."""
    v = line.get(key)
    return v.strip() if isinstance(v, str) and v.strip() else ""


def _close(s: str) -> str:
    """마침표가 없으면 붙인다."""
    return s if s[-1] in (".", "다", "요", "!") else s + "."


def _act_frame(act: str) -> str:
    """speech_act 명사/동명사를 '-듯' 형태로 변환한다.

    규칙:
      - 끝이 '기' → '기' 제거 + '듯'  (떠보기 → 떠보듯, 달래기 → 달래듯)
      - 끝이 '임' → '임' → '이듯'      (몰아붙임 → 몰아붙이듯)
      - 그 외       → '하듯' 접미       (선언 → 선언하듯, 고백 → 고백하듯)
    """
    if act.endswith("기"):
        return act[:-1] + "듯"
    if act.endswith("임"):
        return act[:-1] + "이듯"
    return act + "하듯"


def _sentence1(act: str, mode: str, subtext: str) -> str:
    """첫 번째 문장: speech_act 프레임 + delivery_mode, 또는 subtext 앵커."""
    if act and mode:
        return _close(f"{_act_frame(act)} {mode}")
    if act:
        return _close(_act_frame(act))
    if mode:
        return _close(mode)
    if subtext:
        return _close(subtext)
    return ""


def _sentence2(ending: str, breaks: str) -> str:
    """두 번째 문장: ending_shape 끝처리 + phrase_breaks 내부 끊김."""
    tokens: list[str] = []
    ending_instr = _ENDING_MAP.get(ending, "")
    if ending_instr:
        tokens.append(ending_instr)
    if breaks:
        tokens.append(_close(breaks))
    return " ".join(tokens)
