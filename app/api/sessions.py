"""Rehearsal session API.

GET    /api/sessions          — 저장된 세션 목록 (최신순)
GET    /api/sessions/{id}     — 세션 상세 (audio 파일 존재 검증 포함)
POST   /api/sessions          — 세션 저장 / 업데이트
DELETE /api/sessions/{id}     — 세션 삭제
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.services.session_store import (
    delete_session,
    list_sessions,
    load_session,
    save_session,
)
from app.utils.response import json_response

router = APIRouter()


@router.get("/sessions")
async def get_sessions():
    return json_response({"sessions": list_sessions()})


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    data = load_session(session_id)
    if not data:
        raise HTTPException(404, "세션을 찾을 수 없습니다.")

    # audio 파일 존재 여부 검증 — 없는 파일은 audio_map에서 제거
    raw_map = data.get("audio_map") or {}
    valid_map = {
        k: v for k, v in raw_map.items()
        if Path(v.lstrip("/")).exists()
    }
    if len(valid_map) < len(raw_map):
        print(
            f"[Session] {session_id}: audio {len(raw_map) - len(valid_map)}개 파일 없음 → 제거"
        )
    data["audio_map"] = valid_map

    return json_response(data)


@router.post("/sessions")
async def upsert_session(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "올바른 JSON 형식이 아닙니다.")
    saved = save_session(data)
    print(f"[Session] 저장 완료: {saved['session_id']} ({saved.get('title', '')})")
    return json_response({"session_id": saved["session_id"]})


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    delete_session(session_id)
    return json_response({"message": "삭제 완료"})
