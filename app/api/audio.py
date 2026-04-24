"""오디오 생성 엔드포인트.

POST /api/generate-rehearsal  — 전체 대본 AI 줄 일괄 생성
POST /api/generate-line       — 단일 줄 생성 (미리듣기 포함)
DELETE /api/session/{id}      — 세션 파일 정리
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

from app.schemas.requests import GenerateRehearsalRequest, SingleLineRequest
from app.schemas.responses import ElevenLabsCheckResponse, GenerateLineResponse, GenerateRehearsalResponse, MessageResponse
from app.services.audio_storage import audio_exists, audio_get_url
from app.services.job_runner import run_job
from app.services.tts import check_elevenlabs_auth, delete_session_files, generate_tts_file
from app.utils.audio_paths import rehearsal_audio_path, single_line_audio_path
from app.core.config import TTS_PROVIDER
from app.utils.instructions import build_elevenlabs_prompt, build_tts_instructions
from app.utils.response import json_response

router = APIRouter()


def _build_instructions(line: dict, char_desc: str | None) -> str:
    """provider에 따라 TTS 지시 문자열을 조립한다.

    line dict는 api line 항목 또는 SingleLineRequest.model_dump() 결과와 동일한 구조를 가정한다.
    char_desc는 화자의 캐릭터 설명 문자열 (없으면 None).
    """
    if TTS_PROVIDER == "elevenlabs":
        return build_elevenlabs_prompt(
            char_desc=char_desc,
            beat_goal=line.get("beat_goal"),
            subtext=line.get("subtext"),
            tts_direction=line.get("tts_direction"),
            emotion_label=line.get("emotion_label"),
            intensity=line.get("intensity"),
            speech_act=line.get("speech_act"),
            listener_pressure=line.get("listener_pressure"),
            phrase_breaks=line.get("phrase_breaks"),
            ending_shape=line.get("ending_shape"),
            delivery_mode=line.get("delivery_mode"),
            avoid=line.get("avoid"),
            next_cue_delay_ms=line.get("next_cue_delay_ms"),
        )
    return build_tts_instructions(
        char_desc=char_desc,
        emotion_label=line.get("emotion_label"),
        intensity=line.get("intensity"),
        tempo=line.get("tempo"),
        beat_goal=line.get("beat_goal"),
        tactics=line.get("tactics"),
        subtext=line.get("subtext"),
        tts_direction=line.get("tts_direction"),
        emotion=line.get("emotion"),
        avoid=line.get("avoid"),
    )


@router.post("/generate-rehearsal", response_model=GenerateRehearsalResponse)
async def generate_rehearsal(req: GenerateRehearsalRequest):
    session_id = req.session_id or str(uuid.uuid4())

    total_lines = len(req.lines)
    dialogue_lines = sum(1 for l in req.lines if l.type == "dialogue" and l.character != req.user_character)
    logger.info("[Gen] generate-rehearsal 시작 — total_lines=%d, ai_dialogue=%d, session=%s",
                total_lines, dialogue_lines, session_id[:8])

    # 자격 있는 라인 사전 필터
    pending: list[tuple[int, dict]] = []
    for idx, line in enumerate(req.lines):
        if line.type != "dialogue":
            continue
        char = line.character or ""
        if char == req.user_character:
            continue
        if not req.voice_assignments.get(char):
            continue
        pending.append((idx, line.model_dump()))

    def _generate_one(idx: int, line: dict) -> tuple[str, str] | None:
        """한 라인의 TTS를 생성하고 (str(idx), url) 을 반환. 실패 시 None."""
        char = line.get("character", "")
        voice_id = req.voice_assignments.get(char)
        try:
            instructions = _build_instructions(line, req.character_descriptions.get(char))
            audio_path = rehearsal_audio_path(
                session_id, idx, char, line.get("text", ""), instructions, voice_id or ""
            )
            if audio_exists(audio_path):
                return str(idx), audio_get_url(audio_path)

            # ElevenLabs prosody 개선을 위해 인접 대사 텍스트 추출
            prev_text: str | None = None
            next_text: str | None = None
            if TTS_PROVIDER == "elevenlabs":
                if idx > 0 and req.lines[idx - 1].type == "dialogue":
                    prev_text = req.lines[idx - 1].text
                if idx < len(req.lines) - 1 and req.lines[idx + 1].type == "dialogue":
                    next_text = req.lines[idx + 1].text

            logger.info(
                "[TTS] idx=%d char=%r voice=%s intensity=%s provider=%s\n"
                "  char_desc  : %s\n  beat_goal  : %s\n  subtext    : %s\n"
                "  speech_act : %s\n  ending     : %s\n  norm_hints : %s\n"
                "  pron_hints : %s\n  prompt     : %r%s",
                idx, char, voice_id, line.get('intensity'), TTS_PROVIDER,
                (req.character_descriptions.get(char) or '')[:60],
                line.get('beat_goal') or '-', line.get('subtext') or '-',
                line.get('speech_act') or '-', line.get('ending_shape') or '-',
                (line.get('normalization_hints') or '-')[:60],
                (line.get('pronunciation_hints') or '-')[:60],
                instructions[:120], '…' if len(instructions) > 120 else '',
            )
            generate_tts_file(voice_id, line["text"], instructions, audio_path,
                              intensity=line.get("intensity", 2), line=line,
                              prev_text=prev_text, next_text=next_text)
            return str(idx), audio_get_url(audio_path)
        except Exception as e:
            logger.warning("[Gen] line %d 음성 생성 실패: %s", idx, e)
            return None

    def _run_generate() -> dict:
        audio_map: dict = {}
        if pending:
            # MAX_WORKERS=4 — ElevenLabs rate limit 초과 시 2로 낮출 것
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(_generate_one, idx, line): idx for idx, line in pending}
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        audio_map[result[0]] = result[1]
        return {
            "session_id": session_id,
            "audio_map": audio_map,
            "total_lines": total_lines,
            "user_character": req.user_character,
        }

    _, data = run_job(
        "generate_rehearsal",
        _run_generate,
        session_id=session_id,
        result_summary=lambda d: {
            "session_id": d["session_id"],
            "audio_count": len(d["audio_map"]),
            "total_lines": d["total_lines"],
        },
    )
    return json_response(data)


@router.post("/generate-line", response_model=GenerateLineResponse)
async def generate_single_line(req: SingleLineRequest):
    char = req.character or "char"

    # instructions를 먼저 조립해 올바른 캐시 키(파일 경로)를 얻는다.
    instructions = _build_instructions(req.model_dump(), req.character_description)

    audio_path = single_line_audio_path(
        req.session_id, req.line_index, char, req.text, instructions, req.voice_id or ""
    )

    if not audio_exists(audio_path):
        try:
            line_hints = {
                "pronunciation_hints": req.pronunciation_hints,
                "normalization_hints": req.normalization_hints,
            }
            generate_tts_file(req.voice_id, req.text, instructions, audio_path, intensity=req.intensity or 2, line=line_hints)
        except Exception as e:
            raise HTTPException(500, f"음성 생성 실패: {e}")

    return {"audio_url": audio_get_url(audio_path)}


@router.get("/check-elevenlabs", response_model=ElevenLabsCheckResponse)
async def check_elevenlabs():
    """ElevenLabs API key 설정 및 인증 상태 확인 (개발용)."""
    result = check_elevenlabs_auth()
    return json_response({"provider": "elevenlabs", **result})


@router.delete("/session/{session_id}", response_model=MessageResponse)
async def cleanup_session(session_id: str):
    delete_session_files(session_id)
    return json_response({"message": "세션 삭제 완료"})
