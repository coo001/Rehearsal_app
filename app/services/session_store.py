"""Rehearsal session 저장/불러오기 서비스.

SessionRepository  — 저장소 인터페이스 (ABC)
FileSessionRepository — 파일 기반 구현 (data/sessions/*.json)

모듈 레벨 함수(save_session, load_session 등)는 기본 구현(_repo)에 위임한다.
향후 DB 구현은 SessionRepository를 상속해 _repo에 교체하면 된다.
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 인터페이스 ────────────────────────────────────────────────────

class SessionRepository(ABC):
    @abstractmethod
    def save(self, data: dict) -> dict:
        """session dict를 저장하고 갱신된 dict를 반환. session_id 없으면 신규 발급."""
        ...

    @abstractmethod
    def load(self, session_id: str) -> dict | None:
        """session_id로 로드. 없거나 파싱 실패 시 None."""
        ...

    @abstractmethod
    def list_all(self) -> list[dict]:
        """저장된 세션 목록을 최신순으로 반환 (요약 정보만)."""
        ...

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """session_id 삭제. 존재했으면 True, 없었으면 False."""
        ...


# ── 파일 기반 구현 ────────────────────────────────────────────────

_SESSIONS_DIR = Path("data/sessions")
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class FileSessionRepository(SessionRepository):
    """data/sessions/{session_id}.json 파일 기반 구현."""

    def _path(self, session_id: str) -> Path:
        p = _SESSIONS_DIR / f"{session_id}.json"
        if not p.resolve().is_relative_to(_SESSIONS_DIR.resolve()):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return p

    def save(self, data: dict) -> dict:
        sid = data.get("session_id") or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        data["session_id"] = sid
        data["updated_at"] = now
        data.setdefault("created_at", now)
        self._path(sid).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        line_count = len((data.get("parsed_script") or {}).get("lines") or [])
        logger.info("[Session] 저장 완료 %s... — lines=%d, audio=%d", sid[:8], line_count, len(data.get("audio_map") or {}))
        return data

    def load(self, session_id: str) -> dict | None:
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            line_count = len((data.get("parsed_script") or {}).get("lines") or [])
            logger.info("[Session] 로드 완료 %s... — lines=%d, audio=%d", session_id[:8], line_count, len(data.get("audio_map") or {}))
            return data
        except Exception as e:
            logger.error("[Session] 로드 실패 %s: %s", session_id, e)
            return None

    def list_all(self) -> list[dict]:
        sessions = []
        for p in sorted(_SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", p.stem),
                    "title": data.get("title") or "제목 없음",
                    "updated_at": data.get("updated_at", ""),
                    "user_character": data.get("user_character", ""),
                    "characters": (data.get("parsed_script") or {}).get("characters", []),
                    "audio_count": len(data.get("audio_map") or {}),
                })
            except Exception:
                pass
        return sessions

    def delete(self, session_id: str) -> bool:
        p = self._path(session_id)
        if p.exists():
            p.unlink()
            return True
        return False


# ── 기본 인스턴스 ─────────────────────────────────────────────────

_repo: SessionRepository = FileSessionRepository()


# ── 공개 함수 (하위 호환 유지) ────────────────────────────────────

def save_session(data: dict) -> dict:
    return _repo.save(data)


def load_session(session_id: str) -> dict | None:
    return _repo.load(session_id)


def list_sessions() -> list[dict]:
    return _repo.list_all()


def delete_session(session_id: str) -> bool:
    return _repo.delete(session_id)
