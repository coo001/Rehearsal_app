"""GET /api/voices  |  POST /api/auto-assign-voices."""

import traceback

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
        print("[API] auto-assign-voices — 캐릭터 목록 비어 있음, 빈 배정 반환")
        return json_response({"assignments": {}})

    print(f"[API] auto-assign-voices — chars={req.characters}")

    try:
        result = auto_assign_voices(req.characters, req.character_descriptions, req.user_preferences)
        return json_response(result)
    except ValueError as e:
        print(f"[API] auto-assign-voices 검증 실패: {e}")
        raise HTTPException(422, str(e))
    except Exception as e:
        print(f"[API] auto-assign-voices 예외: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        raise HTTPException(500, f"자동 매핑 중 예외 발생: {type(e).__name__}: {e}")
