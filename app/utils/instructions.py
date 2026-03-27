"""TTS 발화 지시문 빌더 — 순수 함수, 독립적으로 테스트 가능.

설계 원칙:
- 상황 앵커 1문장으로 시작 — 금지 규칙·meta 지시 없음
- 강도 형용사: 짧고 물리적인 단어 사용
- 필드 레이블 최소화 — 값 자체가 디렉션이면 레이블 생략
- 기본값("보통" 속도) 생략, "속도:" 레이블도 생략
- 구분자 \n
"""


def build_tts_instructions(
    char_desc: str | None,          # 하위 호환: 더 이상 instruction에 포함하지 않음
    emotion_label: str | None = None,
    intensity: int | None = None,   # 1(절제) ~ 5(강렬)
    tempo: str | None = None,       # "느리게" | "보통" | "빠르게"
    beat_goal: str | None = None,   # 지금 상대에게서 얻으려는 것
    tactics: str | None = None,     # 하위 호환: 더 이상 포함하지 않음
    subtext: str | None = None,     # 말 아래 숨겨진 압박/의미
    tts_direction: str | None = None,
    emotion: str | None = None,     # 하위 호환: 구형 단일 emotion 문자열
) -> str:
    # ElevenLabs 경로와 동일한 간결한 구조 유지
    # char_desc / tactics는 analytical → TTS 기계적 읽기 유발 → 제거
    # 감정은 intensity 3 이상만 명시 (기본은 절제)
    parts = ["상대를 보며 직접 말하듯. 읽지 말고, 생각이 말이 되게."]

    if beat_goal:
        parts.append(f"원하는 것: {beat_goal}")

    if subtext:
        parts.append(f"말 아래: {subtext}")

    # intensity 3 이상만 감정 명시 (기본 2는 절제로 간주)
    if emotion_label and intensity is not None and intensity >= 3:
        level = ["", "", "드러나는", "강한", "폭발적인"][max(0, min(4, intensity - 1))]
        parts.append(f"{level} {emotion_label}.")
    elif emotion and not emotion_label and intensity is not None and intensity >= 3:
        parts.append(emotion)

    if tts_direction:
        parts.append(tts_direction)

    if tempo and tempo != "보통":
        parts.append(tempo)

    return "\n".join(parts)


def build_elevenlabs_prompt(
    char_desc: str | None = None,
    beat_goal: str | None = None,
    subtext: str | None = None,
    tts_direction: str | None = None,
    emotion_label: str | None = None,
    intensity: int | None = None,
) -> str:
    """ElevenLabs용 발화 지시 문자열.

    구조: 앵커 → 캐릭터 태도 → 목적 → 서브텍스트 → 전달 방식 → (강한 감정만)
    필드가 없으면 해당 줄 생략. intensity < 3이면 감정 줄 생략.
    """
    parts = ["상대에게 직접 말하듯. 읽지 말고, 생각이 말이 되게."]

    if char_desc:
        parts.append(f"이 인물: {char_desc}")

    if beat_goal:
        parts.append(f"원하는 것: {beat_goal}")

    if subtext:
        parts.append(f"말 아래: {subtext}")

    if tts_direction:
        parts.append(tts_direction)

    # 강한 감정만 명시 (intensity 3 이상)
    if emotion_label and intensity is not None and intensity >= 3:
        level = ["", "", "드러나는", "강한", "폭발적인"][max(0, min(4, intensity - 1))]
        parts.append(f"{level} {emotion_label}.")

    return "\n".join(parts)
