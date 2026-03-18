"""TTS 음성 생성 및 세션 파일 관리."""

import shutil
from pathlib import Path

from app.core.config import client, AUDIO_DIR


def generate_tts_file(voice_id: str, text: str, instructions: str, audio_path: Path) -> None:
    """OpenAI TTS 호출 후 audio_path에 mp3로 저장."""
    tts_response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice_id,
        input=text,
        instructions=instructions,
        response_format="mp3",
    )
    tts_response.stream_to_file(str(audio_path))


def delete_session_files(session_id: str) -> None:
    """세션 디렉토리와 하위 파일 전체 삭제."""
    session_dir = AUDIO_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
