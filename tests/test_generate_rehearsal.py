"""Tests for generate_rehearsal endpoint — provider failure handling.

외부 API(ElevenLabs/OpenAI TTS)를 mock해서 검증한다.

핵심 회귀:
- TTS 실패한 라인은 audio_map에서 누락되어야 하되 응답 자체는 200이어야 한다
- 일부 실패가 전체 실패로 번지면 안 된다 (partial success 보장)
- user_character 라인은 절대 생성 시도되지 않아야 한다
- voice_assignments 미지정 캐릭터는 건너뛰어야 한다
"""
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_SESSION = str(uuid.uuid4())

SAMPLE_LINES = [
    {"type": "dialogue", "character": "민수", "text": "안녕하세요."},
    {"type": "dialogue", "character": "지수", "text": "반갑습니다."},
    {"type": "dialogue", "character": "USER", "text": "저는 사용자입니다."},
    {"type": "stage_direction", "text": "(무대 지시)"},
]

BASE_PAYLOAD = {
    "session_id": VALID_SESSION,
    "lines": SAMPLE_LINES,
    "voice_assignments": {"민수": "voice_minsu", "지수": "voice_jisu"},
    "user_character": "USER",
    "character_descriptions": {"민수": "차분한 남성", "지수": "활발한 여성"},
}


def _patch_tts(side_effect=None):
    """generate_tts_file을 mock으로 교체. side_effect로 예외 주입 가능."""
    return patch(
        "app.api.audio.generate_tts_file",
        side_effect=side_effect or (lambda *a, **kw: None),
    )


def _patch_audio_path_exists(exists: bool):
    """audio_path.exists()가 항상 False를 반환하게 해 캐시 히트를 억제."""
    from pathlib import Path
    original_exists = Path.exists

    def patched_exists(self):
        # 테스트용 임시 경로는 실제로 없으므로 그냥 False 반환
        return False

    return patch.object(Path, "exists", patched_exists)


class TestGenerateRehearsalSuccess:
    def test_returns_200_with_audio_map(self):
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert "audio_map" in body
        assert body["user_character"] == "USER"

    def test_user_character_lines_not_in_audio_map(self):
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)
        body = resp.json()
        # USER 라인은 idx 2 — audio_map에 있으면 안 됨
        assert "2" not in body["audio_map"]

    def test_stage_direction_not_in_audio_map(self):
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)
        body = resp.json()
        # stage_direction(idx 3)은 생성 대상 아님
        assert "3" not in body["audio_map"]

    def test_unassigned_character_not_generated(self):
        payload = {**BASE_PAYLOAD, "voice_assignments": {"민수": "v1"}}  # 지수 제외
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=payload)
        body = resp.json()
        # 지수(idx 1)는 voice_assignments 없으므로 건너뜀
        assert "1" not in body["audio_map"]

    def test_session_id_echoed_in_response(self):
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)
        assert resp.json()["session_id"] == VALID_SESSION

    def test_session_id_auto_assigned_when_missing(self):
        payload = {**BASE_PAYLOAD}
        del payload["session_id"]
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=payload)
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        assert len(sid) == 36  # UUID4 형식


class TestGenerateRehearsalPartialFailure:
    def test_single_tts_failure_does_not_fail_entire_request(self):
        call_count = {"n": 0}

        def flaky_tts(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("ElevenLabs 일시 오류")

        with _patch_tts(side_effect=flaky_tts):
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)

        # 전체 실패가 아닌 200 반환
        assert resp.status_code == 200

    def test_all_tts_failures_still_returns_200(self):
        with _patch_tts(side_effect=RuntimeError("모두 실패")):
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["audio_map"] == {}

    def test_failed_lines_absent_from_audio_map(self):
        def always_fail(*args, **kwargs):
            raise RuntimeError("항상 실패")

        with _patch_tts(side_effect=always_fail):
            resp = client.post("/api/generate-rehearsal", json=BASE_PAYLOAD)

        body = resp.json()
        # ai 라인(0, 1)이 audio_map에 없어야 함
        assert "0" not in body["audio_map"]
        assert "1" not in body["audio_map"]


class TestGenerateRehearsalRequestValidation:
    def test_missing_required_field_returns_422(self):
        payload = {k: v for k, v in BASE_PAYLOAD.items() if k != "user_character"}
        resp = client.post("/api/generate-rehearsal", json=payload)
        assert resp.status_code == 422

    def test_empty_lines_returns_200_with_empty_map(self):
        payload = {**BASE_PAYLOAD, "lines": []}
        with _patch_tts():
            resp = client.post("/api/generate-rehearsal", json=payload)
        assert resp.status_code == 200
        assert resp.json()["audio_map"] == {}
