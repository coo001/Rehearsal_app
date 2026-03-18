"""GET /api/voices  |  POST /api/auto-assign-voices."""

from fastapi import APIRouter, HTTPException

from app.core.config import TTS_VOICES
from app.schemas.requests import AutoAssignRequest
from app.services.voice_assigner import auto_assign_voices
from app.utils.response import json_response

router = APIRouter()


@router.get("/voices")
async def get_voices():
    return json_response({"voices": TTS_VOICES})


@router.post("/auto-assign-voices")
async def auto_assign_voices_endpoint(req: AutoAssignRequest):
    if not req.characters:
        return json_response({"assignments": {}})
    try:
        result = auto_assign_voices(req.characters, req.character_descriptions, req.user_preferences)
        return json_response(result)
    except Exception as e:
        raise HTTPException(500, f"자동 배정 실패: {e}")
