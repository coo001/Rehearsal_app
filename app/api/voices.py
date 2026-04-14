"""GET /api/voices  |  POST /api/auto-assign-voices."""

import logging
import traceback

from fastapi import APIRouter, HTTPException

from app.core.config import TTS_VOICES
from app.schemas.requests import AutoAssignRequest
from app.services.voice_assigner import auto_assign_voices
from app.utils.response import json_response

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/voices")
async def get_voices():
    return json_response({"voices": TTS_VOICES})


@router.post("/auto-assign-voices")
async def auto_assign_voices_endpoint(req: AutoAssignRequest):
    if not req.characters:
        logger.info("[API] auto-assign-voices — 캐릭터 목록 비어 있음, 빈 배정 반환")
        return json_response({"assignments": {}})

    logger.info("[API] auto-assign-voices — chars=%s", req.characters)

    try:
        result = auto_assign_voices(req.characters, req.character_descriptions, req.user_preferences)
        return json_response(result)
    except ValueError as e:
        logger.warning("[API] auto-assign-voices 검증 실패: %s", e)
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.error("[API] auto-assign-voices 예외: %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
        raise HTTPException(500, f"자동 매핑 중 예외 발생: {type(e).__name__}: {e}")
