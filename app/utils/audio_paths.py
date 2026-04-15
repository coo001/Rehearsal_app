"""오디오 파일 경로 및 파일명 생성 헬퍼.

명명 규칙:
    audio/{session_id}/{idx:03d}_{character_slug}_{content_hash6}.mp3

예시:
    audio/abc123.../003_민수_a1b2c3.mp3       ← 연습 생성
    audio/preview_.../000_char_f47ac1.mp3    ← 단일 미리듣기 (캐릭터 미지정)
"""

import hashlib
import re
from pathlib import Path

from app.core.config import AUDIO_DIR


def slugify(name: str, max_len: int = 16) -> str:
    """캐릭터명을 파일명 안전 슬러그로 변환.

    - 경로 구분자 및 셸 위험 문자 제거
    - 공백 → 언더스코어
    - 한국어 문자 그대로 보존 (가독성)
    """
    slug = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "", name)
    slug = re.sub(r"\s+", "_", slug.strip())
    return slug[:max_len] or "char"


def content_hash(text: str, instructions: str = "", voice_id: str = "") -> str:
    """TTS 입력의 SHA-1 앞 6자리.

    text만 해싱하면 동일 텍스트지만 다른 지시문/음성일 때 캐시가 오염된다.
    instructions + voice_id를 포함해 캐시 키를 명확히 구분한다.
    """
    payload = "|".join([text, instructions, voice_id])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:6]


def rehearsal_audio_path(
    session_id: str,
    idx: int,
    character: str,
    text: str,
    instructions: str = "",
    voice_id: str = "",
) -> Path:
    """연습 세션용 오디오 경로.

    예: audio/abc123.../003_민수_a1b2c3.mp3

    instructions + voice_id를 해시에 포함하므로 동일 대사라도
    음성 설정이 바뀌면 다른 파일로 분리된다.
    """
    slug = slugify(character)
    h = content_hash(text, instructions, voice_id)
    filename = f"{idx:03d}_{slug}_{h}.mp3"
    return AUDIO_DIR / session_id / filename


def single_line_audio_path(
    session_id: str,
    idx: int,
    character: str,
    text: str,
    instructions: str = "",
    voice_id: str = "",
) -> Path:
    """단일 줄 생성(미리듣기 포함)용 오디오 경로."""
    return rehearsal_audio_path(session_id, idx, character, text, instructions, voice_id)


def audio_url(path: Path) -> str:
    """Path 객체 → 웹 접근 URL 문자열.

    예: Path("audio/abc/003_민수_a1b2c3.mp3") → "/audio/abc/003_민수_a1b2c3.mp3"
    """
    return "/" + path.as_posix()
