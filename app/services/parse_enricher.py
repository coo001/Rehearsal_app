"""LLM 기반 대본 enrichment.

enrich_meta  — character_analysis + relationships (단일 API 호출)
enrich_lines — 각 대화 라인에 beat_goal / subtext / tts_direction 추가 (배치 병렬)
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.config import client, OPENAI_ENRICH_MODEL
from app.prompts.templates import ENRICH_LINES_SYSTEM, ENRICH_META_SYSTEM

logger = logging.getLogger(__name__)

ENRICH_LINES_BATCH_SIZE = 30
ENRICH_LINES_MAX_TOKENS = 2_500
MAX_ENRICH_CHARS = 4  # enrich_meta에서 분석할 최대 캐릭터 수


def enrich_meta(merged: dict) -> dict:
    """병합 결과에 character_analysis + relationships를 단일 API 호출로 추가.

    실패 시 빈 dict로 fallback — 리허설 흐름은 character_analysis 없이도 동작.
    """
    chars = merged.get("characters") or []
    if not chars:
        merged.setdefault("character_analysis", {})
        merged.setdefault("relationships", {})
        return merged

    if len(chars) > MAX_ENRICH_CHARS:
        line_counts: dict[str, int] = {}
        for line in merged.get("lines") or []:
            c = line.get("character")
            if c:
                line_counts[c] = line_counts.get(c, 0) + 1
        chars = sorted(chars, key=lambda c: line_counts.get(c, 0), reverse=True)[:MAX_ENRICH_CHARS]
        logger.info("[Parser] Meta enrich: 캐스트 많음 → 상위 %d명만 분석", MAX_ENRICH_CHARS)

    descs = merged.get("character_descriptions") or {}
    chars_info = "\n".join(f"- {c}: {descs.get(c, '설명 없음')}" for c in chars)
    prompt = f"캐릭터 목록:\n{chars_info}"

    max_enrich_tokens = min(3_000, max(1_200, len(chars) * 700))

    try:
        response = client.chat.completions.create(
            model=OPENAI_ENRICH_MODEL,
            messages=[
                {"role": "system", "content": ENRICH_META_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.3,
            max_tokens=max_enrich_tokens,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        enrich = json.loads(raw)
        merged["character_analysis"] = enrich.get("character_analysis") or {}
        merged["relationships"] = enrich.get("relationships") or {}
        logger.info("[Parser] Meta enrich 완료 - 캐릭터 %d명 (max_tokens=%d)", len(chars), max_enrich_tokens)
    except Exception as e:
        logger.warning("[Parser] Meta enrich 실패 (fallback 빈 dict): %s", e)
        merged.setdefault("character_analysis", {})
        merged.setdefault("relationships", {})

    return merged


def enrich_lines(merged: dict) -> dict:
    """대화 라인에 beat_goal, subtext, tts_direction을 배치 병렬로 추가.

    실패한 배치는 건너뜀 — 리허설 범위는 항상 유지.
    """
    lines = merged.get("lines") or []
    char_analysis = merged.get("character_analysis") or {}
    relationships = merged.get("relationships") or {}

    dialogue_indices = [i for i, line in enumerate(lines) if line.get("type") == "dialogue"]
    if not dialogue_indices:
        return merged

    context = json.dumps(
        {"character_analysis": char_analysis, "relationships": relationships},
        ensure_ascii=False,
    )

    batches = [
        dialogue_indices[i: i + ENRICH_LINES_BATCH_SIZE]
        for i in range(0, len(dialogue_indices), ENRICH_LINES_BATCH_SIZE)
    ]

    def _enrich_batch(batch_indices: list[int]) -> dict[int, dict]:
        batch_lines = [
            {
                "idx": i,
                "char": lines[i].get("character"),
                "text": lines[i].get("text"),
                "emotion_label": lines[i].get("emotion_label"),
                "intensity": lines[i].get("intensity", 2),
            }
            for i in batch_indices
        ]
        user_content = context + "\n\nLines:\n" + json.dumps(batch_lines, ensure_ascii=False)
        try:
            response = client.chat.completions.create(
                model=OPENAI_ENRICH_MODEL,
                messages=[
                    {"role": "system", "content": ENRICH_LINES_SYSTEM},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.3,
                max_tokens=ENRICH_LINES_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            result = json.loads(raw)
            return {int(k): v for k, v in (result.get("results") or {}).items()}
        except Exception as e:
            logger.warning("[Parser] enrich_lines 배치 실패 (fallback): %s", e)
            return {}

    t = time.time()
    all_results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_enrich_batch, batch): batch for batch in batches}
        for future in as_completed(futures):
            all_results.update(future.result())

    enriched = 0
    for idx, perf in all_results.items():
        if idx < len(lines):
            for field in ("beat_goal", "subtext", "tts_direction"):
                val = perf.get(field)
                if val and not lines[idx].get(field):
                    lines[idx][field] = val
            enriched += 1

    merged["lines"] = lines
    logger.info(
        "[Parser] enrich_lines: %.1fs — %d/%d줄 enriched (%d배치)",
        time.time() - t, enriched, len(dialogue_indices), len(batches),
    )
    return merged
