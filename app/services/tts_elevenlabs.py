"""ElevenLabs TTS provider."""

from app.core.config import ELEVENLABS_API_KEY, ELEVENLABS_MODEL_ID

# intensity (1~5) → (stability, style) 기준값
# intensity 1~3: 자연스러운 대화 우선 (style 절제)
# intensity 4~5: 감정이 표면에 올라올 때 style 허용 (최대 0.35)
_INTENSITY_SETTINGS: dict[int, tuple[float, float]] = {
    1: (0.65, 0.05),  # 매우 절제 (평온, 숨김, 무감각)
    2: (0.60, 0.08),  # 차분 (기본 대화, 억제된 감정)
    3: (0.52, 0.13),  # 보통 (감정이 자연스럽게 드러남)
    4: (0.46, 0.25),  # 다소 강함 (감정이 표면에 올라옴)
    5: (0.42, 0.35),  # 강렬 (최대 — 장면 전체에서 드물게)
}

# speech_mode → (stability_delta, style_delta)
_SPEECH_MODE_OFFSETS: dict[str, tuple[float, float]] = {
    "restrained": (+0.08, -0.05),
    "neutral":    ( 0.00,  0.00),
    "pressing":   (-0.07, +0.07),
    "hesitant":   (+0.05, -0.03),
    "cutting":    (-0.05, +0.04),
}


def _voice_hints(instructions: str, listener_pressure: str | None = None) -> tuple[float, float]:
    """instructions + listener_pressure에서 (stability_delta, style_delta) 반환."""
    if not instructions:
        return 0.0, 0.0

    t = instructions.lower()
    s, st = 0.0, 0.0

    if '삼킴' in t or '눌림' in t:
        s += 0.05
    elif '올라감' in t or '열림' in t or '흘러나감' in t:
        s -= 0.03

    if listener_pressure == "강함":
        s -= 0.05
        st += 0.05

    if '속삭' in t or '낮게' in t:
        s += 0.08
        st -= 0.05
    elif '거칠' in t or '급' in t or '몰아' in t:
        s -= 0.04
        st += 0.04

    return s, st


def generate_elevenlabs(
    voice_id: str,
    text: str,
    instructions: str,
    intensity: int,
    speech_mode: str = "neutral",
    prev_text: str | None = None,
    next_text: str | None = None,
    listener_pressure: str | None = None,
) -> bytes:
    """ElevenLabs TTS 호출 후 mp3 bytes 반환. 파일 저장은 호출자(tts.py)가 담당.

    3단 voice_settings 결정:
      1) intensity(1~5) 기준값
      2) speech_mode 보조 축 offset
      3) instruction signal 미세 조정

    prev_text/next_text: 앞뒤 대사 컨텍스트 — ElevenLabs가 prosody 결정에 활용.
    """
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY가 설정되지 않았습니다.")

    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    stability, style = _INTENSITY_SETTINGS.get(max(1, min(5, intensity)), (0.60, 0.08))

    s_mode, st_mode = _SPEECH_MODE_OFFSETS.get(speech_mode, (0.0, 0.0))
    stability += s_mode
    style     += st_mode

    s_delta, st_delta = _voice_hints(instructions, listener_pressure=listener_pressure)
    stability = max(0.20, min(0.90, stability + s_delta))
    style     = max(0.00, min(0.35, style     + st_delta))

    el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    audio_iter = el_client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=ELEVENLABS_MODEL_ID,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=0.78,
            style=style,
            use_speaker_boost=True,
        ),
        previous_text=prev_text,
        next_text=next_text,
    )
    return b"".join(audio_iter)
