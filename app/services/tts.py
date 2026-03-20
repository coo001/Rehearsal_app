"""TTS 음성 생성 및 세션 파일 관리."""

import shutil
from pathlib import Path

from app.core.config import (
    AUDIO_DIR,
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL_ID,
    TTS_PROVIDER,
    client,
)


def generate_tts_file(
    voice_id: str,
    text: str,
    instructions: str,
    audio_path: Path,
    intensity: int = 2,
) -> None:
    """TTS_PROVIDER에 따라 OpenAI 또는 ElevenLabs로 음성 생성 후 mp3 저장."""
    if TTS_PROVIDER == "elevenlabs":
        _generate_elevenlabs(voice_id, text, instructions, audio_path, intensity)
    else:
        _generate_openai(voice_id, text, instructions, audio_path)


def _generate_openai(voice_id: str, text: str, instructions: str, audio_path: Path) -> None:
    tts_response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice_id,
        input=text,
        instructions=instructions,
        response_format="mp3",
    )
    tts_response.stream_to_file(str(audio_path))


def _generate_elevenlabs(
    voice_id: str,
    text: str,
    instructions: str,
    audio_path: Path,
    intensity: int,
) -> None:
    """ElevenLabs TTS 호출.

    intensity(1~5)를 voice_settings로 변환:
    - 1~2: stability 높음, style 낮음 (절제된 전달)
    - 3:   balanced
    - 4~5: stability 낮음, style 높음 (표현력 극대화)
    """
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY가 설정되지 않았습니다.")

    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    # intensity -> voice_settings 매핑
    if intensity <= 2:
        stability, style = 0.65, 0.15
    elif intensity == 3:
        stability, style = 0.50, 0.35
    else:
        stability, style = 0.30, 0.60

    el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    audio_iter = el_client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=ELEVENLABS_MODEL_ID,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=0.75,
            style=style,
            use_speaker_boost=True,
        ),
    )
    audio_path.write_bytes(b"".join(audio_iter))


def delete_session_files(session_id: str) -> None:
    """세션 디렉토리와 하위 파일 전체 삭제."""
    session_dir = AUDIO_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)


def check_elevenlabs_auth() -> dict:
    """ElevenLabs API key 설정 여부와 인증 성공 여부를 반환.

    실제 키 값은 절대 노출하지 않는다.
    반환: {"configured": bool, "auth_ok": bool, "detail": str}
    """
    if not ELEVENLABS_API_KEY:
        return {
            "configured": False,
            "auth_ok": False,
            "detail": "ELEVENLABS_API_KEY is missing.",
        }

    try:
        from elevenlabs.client import ElevenLabs
        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        el_client.user.get()
        return {
            "configured": True,
            "auth_ok": True,
            "detail": "ElevenLabs API authentication succeeded.",
        }
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg:
            detail = "Authentication failed with ElevenLabs API."
        elif "connection" in msg or "timeout" in msg or "network" in msg:
            detail = "Connection error reaching ElevenLabs API."
        else:
            detail = f"ElevenLabs API check failed: {type(e).__name__}"
        return {
            "configured": True,
            "auth_ok": False,
            "detail": detail,
        }
