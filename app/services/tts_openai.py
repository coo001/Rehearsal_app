"""OpenAI TTS provider."""

from pathlib import Path

from app.core.config import client, OPENAI_TTS_MODEL


def generate_openai(voice_id: str, text: str, instructions: str, audio_path: Path) -> None:
    """OpenAI TTS 호출 후 mp3 저장."""
    tts_response = client.audio.speech.create(
        model=OPENAI_TTS_MODEL,
        voice=voice_id,
        input=text,
        instructions=instructions,
        response_format="mp3",
    )
    tts_response.stream_to_file(str(audio_path))
