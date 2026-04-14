"""TTS 음성 생성 오케스트레이션 및 세션 파일 관리.

generate_tts_file()  — 공개 진입점, provider 분기
delete_session_files() — 세션 오디오 디렉토리 삭제
check_elevenlabs_auth() — ElevenLabs 인증 상태 확인 (개발용)
"""

import logging
import shutil
from pathlib import Path

from app.core.config import AUDIO_DIR, ELEVENLABS_API_KEY, TTS_PROVIDER
from app.services.tts_elevenlabs import generate_elevenlabs
from app.services.tts_openai import generate_openai
from app.services.tts_text import TtsInput, build_tts_input, format_text_for_elevenlabs

logger = logging.getLogger(__name__)


def generate_tts_file(
    voice_id: str,
    text: str,
    instructions: str,
    audio_path: Path,
    intensity: int = 2,
    line: dict | None = None,
) -> None:
    """TTS_PROVIDER에 따라 OpenAI 또는 ElevenLabs로 음성 생성 후 mp3 저장."""
    text_original = text
    if TTS_PROVIDER == "elevenlabs":
        text = format_text_for_elevenlabs(text, line)
    tts = build_tts_input(text, instructions, intensity)
    _log_tts_preview(TTS_PROVIDER, voice_id, text_original, tts, line)
    if TTS_PROVIDER == "elevenlabs":
        generate_elevenlabs(voice_id, tts.cleaned_text, tts.instructions, audio_path, tts.intensity, tts.speech_mode)
    else:
        _log_openai_input(voice_id, tts.cleaned_text, tts.instructions)
        generate_openai(voice_id, tts.cleaned_text, tts.instructions, audio_path)


def delete_session_files(session_id: str) -> None:
    """세션 디렉토리와 하위 파일 전체 삭제."""
    session_dir = AUDIO_DIR / session_id
    if not session_dir.resolve().is_relative_to(AUDIO_DIR.resolve()):
        raise ValueError(f"Invalid session_id: {session_id!r}")
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
        logger.warning("[TTS] ElevenLabs 인증 확인 실패: %s", detail)
        return {
            "configured": True,
            "auth_ok": False,
            "detail": detail,
        }


# ── 로그 헬퍼 ────────────────────────────────────────────────────

def _log_openai_input(voice_id: str, text: str, instructions: str) -> None:
    logger.info(
        "[TTS] provider=openai voice=%s\n  text        : %r%s\n  instructions: %r%s",
        voice_id,
        text[:80], "..." if len(text) > 80 else "",
        instructions[:120], "..." if len(instructions) > 120 else "",
    )


def _log_tts_preview(
    provider: str,
    voice_id: str,
    text_original: str,
    tts: TtsInput,
    line: dict | None,
) -> None:
    norm  = ((line or {}).get("normalization_hints") or "").strip()
    pron  = ((line or {}).get("pronunciation_hints") or "").strip()
    deliv = ((line or {}).get("delivery_mode") or "").strip()
    text_changed = text_original.strip() != tts.cleaned_text.strip()

    rows = [
        f"[TTS:preview] {provider} · voice={voice_id} · intensity={tts.intensity} · mode={tts.speech_mode}",
        f"  text      : {tts.cleaned_text[:80]!r}{'…' if len(tts.cleaned_text) > 80 else ''}",
    ]
    if text_changed:
        rows.append(
            f"  text_orig : {text_original[:60]!r}{'…' if len(text_original) > 60 else ''}  ← formatted"
        )
    rows += [
        f"  instruct  : {tts.instructions[:120]!r}{'…' if len(tts.instructions) > 120 else ''}",
        f"  delivery  : {deliv or '-'}",
        f"  norm_hints: {norm[:80] or '-'}",
        f"  pron_hints: {pron[:80] or '-'}",
    ]
    logger.info("\n".join(rows))
