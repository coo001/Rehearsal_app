"""Rehearsal session 저장/불러오기 서비스.

저장 위치: data/sessions/{session_id}.json
오디오 파일 자체는 저장하지 않고 경로(audio_map)만 저장한다.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

SESSIONS_DIR = Path("data/sessions")
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _path(session_id: str) -> Path:
    p = SESSIONS_DIR / f"{session_id}.json"
    if not p.resolve().is_relative_to(SESSIONS_DIR.resolve()):
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return p


def save_session(data: dict) -> dict:
    """session dict를 JSON 파일로 저장. session_id 없으면 신규 발급."""
    sid = data.get("session_id") or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    data["session_id"] = sid
    data["updated_at"] = now
    data.setdefault("created_at", now)
    _path(sid).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    line_count = len((data.get("parsed_script") or {}).get("lines") or [])
    print(f"[Session] 저장 완료 {sid[:8]}... — lines={line_count}, audio={len(data.get('audio_map') or {})}")
    return data


def load_session(session_id: str) -> dict | None:
    """JSON 파일에서 session 로드. 없거나 파싱 실패 시 None."""
    p = _path(session_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        line_count = len((data.get("parsed_script") or {}).get("lines") or [])
        print(f"[Session] 로드 완료 {session_id[:8]}... — lines={line_count}, audio={len(data.get('audio_map') or {})}")
        return data
    except Exception as e:
        print(f"[Session] 로드 실패 {session_id}: {e}")
        return None


def list_sessions() -> list[dict]:
    """저장된 세션 목록을 최신순으로 반환 (요약 정보만)."""
    sessions = []
    for p in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
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


def delete_session(session_id: str) -> bool:
    p = _path(session_id)
    if p.exists():
        p.unlink()
        return True
    return False
