"""OpenAI TTS provider."""

from app.core.config import client, OPENAI_TTS_MODEL


def generate_openai(voice_id: str, text: str, instructions: str) -> bytes:
    """OpenAI TTS 호출 후 mp3 bytes 반환. 파일 저장은 호출자(tts.py)가 담당."""
    tts_response = client.audio.speech.create(
        model=OPENAI_TTS_MODEL,
        voice=voice_id,
        input=text,
        instructions=instructions,
        response_format="mp3",
    )
    return tts_response.content
