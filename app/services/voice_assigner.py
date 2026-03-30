"""GPT-4o 자동 목소리 배정 서비스."""

import json

from app.core.config import client, TTS_VOICES, VALID_VOICE_IDS, OPENAI_VOICE_ASSIGN_MODEL
from app.prompts.templates import AUTO_ASSIGN_TEMPLATE


def auto_assign_voices(
    characters: list,
    character_descriptions: dict,
    user_preferences: dict | None = None,
) -> dict:
    """캐릭터 목록을 받아 GPT-4o로 voice_id를 배정하고 결과를 반환.

    user_preferences: {"캐릭터명": "더 차분하게"} — 있으면 프롬프트 최우선 섹션에 삽입.
    반환: {"assignments": {"캐릭터명": "voice_id"}, "reasons": {"캐릭터명": "이유"}}
    """
    if not TTS_VOICES:
        raise ValueError("사용 가능한 음성 목록이 비어 있습니다")
    if not characters:
        raise ValueError("배정할 캐릭터 목록이 비어 있습니다")

    print(f"[VoiceAssign] 시작 — chars={len(characters)}{characters}, voices={len(TTS_VOICES)}, model={OPENAI_VOICE_ASSIGN_MODEL}")

    voices_info = "\n".join(
        f"- {v['voice_id']}: {v['name']} | {v['gender']} | {v['description']}"
        for v in TTS_VOICES
    )
    characters_info = "\n".join(
        f"- {c}: {character_descriptions.get(c, '설명 없음')}"
        for c in characters
    )

    prefs = {k: v for k, v in (user_preferences or {}).items() if v and v.strip()}
    if prefs:
        pref_lines = "\n".join(f"- {c}: {p}" for c, p in prefs.items())
        user_preferences_info = f"\n사용자 피드백 (최우선 반영):\n{pref_lines}\n"
    else:
        user_preferences_info = ""

    try:
        response = client.chat.completions.create(
            model=OPENAI_VOICE_ASSIGN_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": AUTO_ASSIGN_TEMPLATE.format(
                        voices_info=voices_info,
                        characters_info=characters_info,
                        user_preferences_info=user_preferences_info,
                    ),
                },
                {"role": "user", "content": "각 캐릭터에 최적의 목소리를 배정해주세요."},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print(f"[VoiceAssign] LLM API 오류: {type(e).__name__}: {e}")
        raise

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[VoiceAssign] JSON 파싱 실패: {e} — raw={raw[:200]}")
        raise ValueError(f"LLM 응답 파싱 실패: {e}")

    # 새 형식 {assignments: {...}, reasons: {...}} 또는 구형 {"캐릭터": "voice_id"} 모두 처리
    assignments = result.get("assignments", result)
    reasons = result.get("reasons", {})
    valid = {k: v for k, v in assignments.items() if v in VALID_VOICE_IDS}

    print(f"[VoiceAssign] 완료 — raw={len(assignments)}, valid={len(valid)}/{len(characters)}")
    if not valid:
        print(f"[VoiceAssign] 경고: 유효한 voice_id 없음. LLM 응답: {assignments}")

    return {"assignments": valid, "reasons": reasons}
