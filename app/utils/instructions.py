"""TTS 발화 지시문 빌더 — 순수 함수, 독립적으로 테스트 가능.

설계 원칙:
- 상황 앵커 1문장으로 시작 — 금지 규칙·meta 지시 없음
- 강도 형용사: 짧고 물리적인 단어 사용
- 필드 레이블 최소화 — 값 자체가 디렉션이면 레이블 생략
- 기본값("보통" 속도) 생략, "속도:" 레이블도 생략
- 구분자 \n
"""


def build_tts_instructions(
    char_desc: str | None,
    emotion_label: str | None = None,
    intensity: int | None = None,   # 1(절제) ~ 5(강렬)
    tempo: str | None = None,       # "느리게" | "보통" | "빠르게"
    beat_goal: str | None = None,   # GOTE Goal: 지금 상대에게서 얻으려는 것
    tactics: str | None = None,     # GOTE Tactics: 상대를 움직이는 방식
    subtext: str | None = None,     # 말 아래 숨겨진 압박/의미
    tts_direction: str | None = None,
    emotion: str | None = None,     # 하위 호환: 구형 단일 emotion 문자열
) -> str:
    parts = []

    # 1. 상황 앵커
    parts.append("상대방을 보며 직접 말하듯. 생각이 말로 흘러나오게.")

    # 2. 캐릭터 발화 태도
    if char_desc:
        parts.append(f"이 인물: {char_desc}")

    # 3. GOTE Goal — 지금 상대에게서 얻으려는 것
    if beat_goal:
        parts.append(f"원하는 것: {beat_goal}")

    # 4. GOTE Tactics — 상대를 움직이는 방식
    if tactics:
        parts.append(f"전술: {tactics}")

    # 5. Subtext — 말 아래 흐르는 것 (드러나지 않는 압박)
    if subtext:
        parts.append(f"말 아래: {subtext}")

    # 6. 감정 상태
    if emotion and not emotion_label:
        parts.append(emotion)
    elif emotion_label:
        if intensity is not None:
            level = ["억눌린", "가라앉은", "드러나는", "강한", "폭발적인"][max(0, min(4, intensity - 1))]
            parts.append(f"감정: {level} {emotion_label}")
        else:
            parts.append(f"감정: {emotion_label}")

    # 6-1. 저강도 음량 가드
    if intensity is not None and intensity <= 2:
        parts.append("목소리가 상대방에게 닿도록. 속삭임 아님.")

    # 7. 속도 — "보통" 생략
    if tempo and tempo != "보통":
        parts.append(tempo)

    # 8. 발화 방식 — 가장 구체적인 마지막 지시
    if tts_direction:
        parts.append(tts_direction)

    return "\n".join(parts)
