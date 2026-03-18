"""GPT-4o 대본 파싱 서비스."""

import json

from app.core.config import client
from app.prompts.templates import PARSE_SCRIPT_SYSTEM


def parse_script(script_text: str) -> dict:
    """대본 텍스트를 GPT-4o로 파싱해 구조화된 dict 반환.

    JSONDecodeError 또는 API 예외는 호출자(route)가 처리한다.
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": PARSE_SCRIPT_SYSTEM},
            {"role": "user",   "content": f"다음 대본을 분석해주세요:\n\n{script_text}"},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)
