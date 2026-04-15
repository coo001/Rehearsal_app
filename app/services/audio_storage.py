"""오디오 파일 저장 추상화.

AudioStorage   — 저장소 인터페이스 (ABC)
LocalAudioStorage — 로컬 파일시스템 구현 (현재 동작 유지)

향후 S3/GCS 구현은 AudioStorage를 상속해 _storage에 교체하면 된다.
path 계산은 audio_paths.py가 담당하고, 저장/조회/삭제 I/O만 여기서 처리한다.
"""

import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import AUDIO_DIR
from app.utils.audio_paths import audio_url

logger = logging.getLogger(__name__)


# ── 인터페이스 ────────────────────────────────────────────────────

class AudioStorage(ABC):
    @abstractmethod
    def exists(self, path: Path) -> bool:
        """파일(또는 오브젝트)이 이미 존재하는지 확인."""
        ...

    @abstractmethod
    def save(self, path: Path, data: bytes) -> None:
        """bytes를 저장한다. 필요한 디렉토리/버킷 경로 생성도 여기서 처리."""
        ...

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """세션에 속한 오디오 파일 전체 삭제."""
        ...

    @abstractmethod
    def get_url(self, path: Path) -> str:
        """저장된 파일의 접근 URL 반환."""
        ...


# ── 로컬 파일시스템 구현 ──────────────────────────────────────────

class LocalAudioStorage(AudioStorage):
    """AUDIO_DIR 하위 로컬 파일시스템 저장소."""

    def exists(self, path: Path) -> bool:
        return path.exists()

    def save(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete_session(self, session_id: str) -> None:
        session_dir = AUDIO_DIR / session_id
        if not session_dir.resolve().is_relative_to(AUDIO_DIR.resolve()):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info("[AudioStorage] 세션 디렉토리 삭제: %s", session_id[:8])

    def get_url(self, path: Path) -> str:
        return audio_url(path)


# ── 기본 인스턴스 ─────────────────────────────────────────────────

_storage: AudioStorage = LocalAudioStorage()


# ── 공개 함수 ─────────────────────────────────────────────────────

def audio_exists(path: Path) -> bool:
    return _storage.exists(path)


def audio_save(path: Path, data: bytes) -> None:
    _storage.save(path, data)


def audio_delete_session(session_id: str) -> None:
    _storage.delete_session(session_id)


def audio_get_url(path: Path) -> str:
    return _storage.get_url(path)
