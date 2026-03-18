"""GPT-4o 자동 목소리 배정 서비스."""

import json

from app.core.config import client, TTS_VOICES, VALID_VOICE_IDS
from app.prompts.templates import AUTO_ASSIGN_TEMPLATE


def auto_assign_voices(characters: list, character_descriptions: dict) -> dict:
    """캐릭터 목록을 받아 GPT-4o로 voice_id를 배정하고 결과를 반환.

    반환: {"assignments": {"캐릭터명": "voice_id"}, "reasons": {"캐릭터명": "이유"}}
    """
    voices_info = "\n".join(
        f"- {v['voice_id']}: {v['name']} | {v['gender']} | {v['description']}"
        for v in TTS_VOICES
    )
    characters_info = "\n".join(
        f"- {c}: {character_descriptions.get(c, '설명 없음')}"
        for c in characters
    )

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
    assignments = {k: v for k, v in assignments.items() if v in VALID_VOICE_IDS}

    return {"assignments": assignments, "reasons": reasons}
