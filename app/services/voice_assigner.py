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
    # ── Step 1/4: 입력 검증 ───────────────────────────────────
    if not TTS_VOICES:
        raise ValueError("사용 가능한 음성 목록이 비어 있습니다")
    if not characters:
        raise ValueError("배정할 캐릭터 목록이 비어 있습니다")
    print(
        f"[VoiceAssign] 1/4 입력 검증 통과 — "
        f"chars={len(characters)} {characters}, voices={len(TTS_VOICES)}, model={OPENAI_VOICE_ASSIGN_MODEL}"
    )

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

    # ── Step 2/4: LLM 호출 ────────────────────────────────────
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
        print(f"[VoiceAssign] 2/4 LLM 호출 실패: {type(e).__name__}: {e}")
        raise

    raw = response.choices[0].message.content or ""
    finish_reason = response.choices[0].finish_reason
    print(
        f"[VoiceAssign] 2/4 LLM 응답 수신 — finish_reason={finish_reason!r}, raw_len={len(raw)}\n"
        f"  raw preview: {raw[:160]!r}"
    )

    # ── Step 3/4: JSON 파싱 ───────────────────────────────────
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[VoiceAssign] 3/4 JSON 파싱 실패: {e} — raw={raw[:200]!r}")
        raise ValueError(f"LLM 응답 파싱 실패: {e}")

    # 새 형식 {assignments: {...}, reasons: {...}} 또는 구형 {"캐릭터": "voice_id"} 모두 처리
    raw_assignments = result.get("assignments", result)
    raw_reasons = result.get("reasons", {})
    n_raw = len(raw_assignments) if isinstance(raw_assignments, dict) else "?"
    print(
        f"[VoiceAssign] 3/4 JSON 파싱 완료 — "
        f"top_keys={list(result.keys())}, assignments={n_raw}개"
    )

    # ── Step 4/4: 응답 정리 및 부분 성공 처리 ────────────────
    valid, reasons = _clean_assignments(raw_assignments, raw_reasons)
    print(f"[VoiceAssign] 4/4 배정 완료 — valid={len(valid)}/{len(characters)}")
    if not valid:
        print("[VoiceAssign] 경고: 유효한 배정 결과 없음 — VALID_VOICE_IDS 목록을 확인하세요")

    # ── Fallback: 미배정 캐릭터를 남은 voice로 채우기 ─────────
    if len(valid) < len(characters):
        fb = _fallback_assignments(characters, valid, VALID_VOICE_IDS)
        if fb:
            print(f"[VoiceAssign] fallback 배정: {list(fb.keys())} → {list(fb.values())}")
            valid.update(fb)
            reasons.update({k: "fallback" for k in fb})

    return {"assignments": valid, "reasons": reasons}


def _fallback_assignments(
    characters: list,
    existing: dict,
    valid_voice_ids: set,
) -> dict:
    """미배정 캐릭터를 남은 valid voice로 순서대로 채운다.

    - LLM이 이미 배정한 voice는 우선 피함 (중복 불가피하면 허용)
    - 완전히 빈 voice 목록이면 빈 dict 반환
    """
    if not valid_voice_ids:
        return {}

    unassigned = [c for c in characters if c not in existing]
    if not unassigned:
        return {}

    used_ids = set(existing.values())
    # 미사용 voice 우선, 없으면 전체 pool에서 순환
    pool = [v for v in valid_voice_ids if v not in used_ids] or list(valid_voice_ids)

    return {char: pool[i % len(pool)] for i, char in enumerate(unassigned)}


def _clean_assignments(
    raw_assignments: object,
    raw_reasons: object,
) -> tuple[dict, dict]:
    """LLM 응답 assignments를 안전하게 정리해 (valid_assignments, reasons) 반환.

    처리 순서:
    1. dict 타입 확인 — 아니면 빈 dict 즉시 반환
    2. key/value 모두 문자열인 항목만 허용, key strip 정규화
    3. VALID_VOICE_IDS 필터 (invalid는 로그 후 제거)
    4. 중복 voice_id 경고 (배정은 유지 — 금지보다 경고 우선)
    5. reasons key도 strip 정규화
    """
    if not isinstance(raw_assignments, dict):
        print(f"[VoiceAssign] assignments 타입 오류: {type(raw_assignments).__name__} (dict 예상) — 빈 dict 반환")
        return {}, {}

    # key/value 문자열 검증 + key strip 정규화
    cleaned: dict[str, str] = {}
    skipped: list = []
    for k, v in raw_assignments.items():
        k_norm = str(k).strip() if k is not None else ""
        if not k_norm:
            skipped.append((k, v, "빈 key"))
            continue
        if not isinstance(v, str):
            skipped.append((k, v, f"비문자열 value({type(v).__name__})"))
            continue
        cleaned[k_norm] = v
    if skipped:
        print(f"[VoiceAssign] 비정상 항목 제거: {skipped}")

    # VALID_VOICE_IDS 필터
    valid = {k: v for k, v in cleaned.items() if v in VALID_VOICE_IDS}
    invalid = {k: v for k, v in cleaned.items() if v not in VALID_VOICE_IDS}
    if invalid:
        print(f"[VoiceAssign] 무효 voice_id 제거 ({len(invalid)}개): {invalid}")

    # 중복 voice_id 경고 (배정 유지)
    seen: dict[str, str] = {}
    for char, vid in valid.items():
        if vid in seen:
            print(f"[VoiceAssign] 중복 voice_id 경고: {char!r}와 {seen[vid]!r} 모두 {vid!r} 배정")
        else:
            seen[vid] = char

    # reasons key strip 정규화 (valid key와 일관성)
    reasons: dict[str, str] = {
        str(k).strip(): v
        for k, v in (raw_reasons if isinstance(raw_reasons, dict) else {}).items()
        if str(k).strip()
    }

    return valid, reasons
