"""POST /api/parse-script — GPT-4o 대본 파싱."""

import json

from fastapi import APIRouter, HTTPException

from app.core.config import client
from app.prompts.templates import PARSE_SCRIPT_SYSTEM
from app.schemas.requests import ParseScriptRequest
from app.utils.response import json_response

router = APIRouter()


@router.post("/parse-script")
async def parse_script(req: ParseScriptRequest):
    if not req.script.strip():
        raise HTTPException(400, "대본 내용을 입력해주세요.")
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": PARSE_SCRIPT_SYSTEM},
                {"role": "user",   "content": f"다음 대본을 분석해주세요:\n\n{req.script}"},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return json_response(data)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"대본 파싱 실패 (JSON 오류): {e}")
    except Exception as e:
        raise HTTPException(500, f"대본 파싱 중 오류: {e}")
