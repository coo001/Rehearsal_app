"""GET /api/voices  |  POST /api/auto-assign-voices."""

import json

from fastapi import APIRouter, HTTPException

from app.core.config import TTS_VOICES, VALID_VOICE_IDS, client
from app.prompts.templates import AUTO_ASSIGN_TEMPLATE
from app.schemas.requests import AutoAssignRequest
from app.utils.response import json_response

router = APIRouter()


@router.get("/voices")
async def get_voices():
    return json_response({"voices": TTS_VOICES})


@router.post("/auto-assign-voices")
async def auto_assign_voices(req: AutoAssignRequest):
    if not req.characters:
        return json_response({"assignments": {}})

    voices_info = "\n".join(
        f"- {v['voice_id']}: {v['name']} | {v['gender']} | {v['description']}"
        for v in TTS_VOICES
    )
    characters_info = "\n".join(
        f"- {c}: {req.character_descriptions.get(c, '설명 없음')}"
        for c in req.characters
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": AUTO_ASSIGN_TEMPLATE.format(
                        voices_info=voices_info,
                        characters_info=characters_info,
                    ),
                },
                {"role": "user", "content": "각 캐릭터에 최적의 목소리를 배정해주세요."},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        # 새 형식 {assignments: {...}, reasons: {...}} 또는 구형 {"캐릭터": "voice_id"} 모두 처리
        assignments = result.get("assignments", result)
        reasons = result.get("reasons", {})
        # 유효한 voice_id만 필터링
        assignments = {k: v for k, v in assignments.items() if v in VALID_VOICE_IDS}
        return json_response({"assignments": assignments, "reasons": reasons})
    except Exception as e:
        raise HTTPException(500, f"자동 배정 실패: {e}")
