"""Tests for session_store path traversal guard and basic CRUD.

session_store._path()는 session_id를 파일 경로로 변환한다.
경로 탐색 공격 방어 코드가 실제로 동작하는지 검증한다.
"""
import json
import uuid

import pytest

import app.services.session_store as store


@pytest.fixture(autouse=True)
def _tmp_sessions(tmp_path, monkeypatch):
    """각 테스트를 격리된 임시 디렉토리에서 실행."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    monkeypatch.setattr(store, "_SESSIONS_DIR", sessions_dir)
    return sessions_dir


class TestPathTraversalGuard:
    def test_valid_uuid_passes(self):
        sid = str(uuid.uuid4())
        # 예외 없이 Path 반환
        path = store._repo._path(sid)
        assert path.suffix == ".json"

    def test_dotdot_traversal_blocked(self):
        with pytest.raises(ValueError, match="Invalid session_id"):
            store._repo._path("../../../etc/passwd")

    def test_dotdot_in_middle_blocked(self):
        with pytest.raises(ValueError, match="Invalid session_id"):
            store._repo._path("abc/../../secret")

    def test_absolute_path_blocked(self):
        with pytest.raises(ValueError, match="Invalid session_id"):
            store._repo._path("/etc/passwd")


class TestSaveAndLoad:
    def test_save_assigns_session_id_if_missing(self):
        saved = store.save_session({"title": "테스트"})
        assert "session_id" in saved
        assert len(saved["session_id"]) > 0

    def test_save_and_load_roundtrip(self):
        sid = str(uuid.uuid4())
        store.save_session({"session_id": sid, "title": "리허설"})
        loaded = store.load_session(sid)
        assert loaded is not None
        assert loaded["title"] == "리허설"

    def test_load_nonexistent_returns_none(self):
        result = store.load_session(str(uuid.uuid4()))
        assert result is None

    def test_save_sets_updated_at(self):
        saved = store.save_session({"title": "타임스탬프 테스트"})
        assert "updated_at" in saved

    def test_delete_removes_file(self):
        sid = str(uuid.uuid4())
        store.save_session({"session_id": sid})
        assert store.delete_session(sid) is True
        assert store.load_session(sid) is None

    def test_delete_nonexistent_returns_false(self):
        assert store.delete_session(str(uuid.uuid4())) is False

    def test_load_handles_corrupt_json_gracefully(self, tmp_path, monkeypatch):
        sessions_dir = tmp_path / "sessions2"
        sessions_dir.mkdir()
        monkeypatch.setattr(store, "_SESSIONS_DIR", sessions_dir)
        sid = str(uuid.uuid4())
        (sessions_dir / f"{sid}.json").write_text("not json", encoding="utf-8")
        result = store.load_session(sid)
        assert result is None


class TestListSessions:
    def test_empty_dir_returns_empty_list(self):
        assert store.list_sessions() == []

    def test_saved_session_appears_in_list(self):
        store.save_session({"title": "목록 테스트"})
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["title"] == "목록 테스트"
