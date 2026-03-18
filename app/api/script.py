"""POST /api/parse-script — GPT-4o 대본 파싱."""

import json

from fastapi import APIRouter, HTTPException

from app.schemas.requests import ParseScriptRequest
from app.services.script_parser import parse_script
from app.utils.response import json_response

router = APIRouter()


@router.post("/parse-script")
async def parse_script_endpoint(req: ParseScriptRequest):
    if not req.script.strip():
        raise HTTPException(400, "대본 내용을 입력해주세요.")
    try:
        data = parse_script(req.script)
        return json_response(data)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"대본 파싱 실패 (JSON 오류): {e}")
    except Exception as e:
        raise HTTPException(500, f"대본 파싱 중 오류: {e}")
