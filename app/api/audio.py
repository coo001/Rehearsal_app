"""오디오 생성 엔드포인트.

POST /api/generate-rehearsal  — 전체 대본 AI 줄 일괄 생성
POST /api/generate-line       — 단일 줄 생성 (미리듣기 포함)
DELETE /api/session/{id}      — 세션 파일 정리
"""

import uuid

from fastapi import APIRouter, HTTPException

from app.schemas.requests import GenerateRehearsalRequest, SingleLineRequest
from app.services.tts import check_elevenlabs_auth, delete_session_files, generate_tts_file
from app.utils.audio_paths import audio_url, rehearsal_audio_path, single_line_audio_path
from app.core.config import TTS_PROVIDER
from app.utils.instructions import build_elevenlabs_prompt, build_tts_instructions
from app.utils.response import json_response

router = APIRouter()


@router.post("/generate-rehearsal")
async def generate_rehearsal(req: GenerateRehearsalRequest):
    session_id = req.session_id or str(uuid.uuid4())
    audio_map: dict = {}

    total_lines = len(req.lines)
    dialogue_lines = sum(1 for l in req.lines if l.get("type") == "dialogue" and l.get("character") != req.user_character)
    print(f"[Gen] generate-rehearsal 시작 — total_lines={total_lines}, ai_dialogue={dialogue_lines}, session={session_id[:8]}")

    for idx, line in enumerate(req.lines):
        if line.get("type") != "dialogue":
            continue
        char = line.get("character", "")
        if char == req.user_character:
            continue

        voice_id = req.voice_assignments.get(char)
        if not voice_id:
            continue

        audio_path = rehearsal_audio_path(session_id, idx, char, line.get("text", ""))

        if audio_path.exists():
            audio_map[str(idx)] = audio_url(audio_path)
            continue

        try:
            if TTS_PROVIDER == "elevenlabs":
                instructions = build_elevenlabs_prompt(
                    char_desc=req.character_descriptions.get(char),
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
            else:
                instructions = build_tts_instructions(
                    char_desc=req.character_descriptions.get(char),
                    emotion_label=line.get("emotion_label"),
                    intensity=line.get("intensity"),
                    tempo=line.get("tempo"),
                    beat_goal=line.get("beat_goal"),
                    tactics=line.get("tactics"),
                    subtext=line.get("subtext"),
                    tts_direction=line.get("tts_direction"),
                    emotion=line.get("emotion"),
                )
            print(
                f"[TTS] idx={idx} char={char!r} voice={voice_id} intensity={line.get('intensity')} provider={TTS_PROVIDER}"
                f"\n  char_desc  : {(req.character_descriptions.get(char) or '')[:60]}"
                f"\n  beat_goal  : {line.get('beat_goal') or '-'}"
                f"\n  subtext    : {line.get('subtext') or '-'}"
                f"\n  speech_act : {line.get('speech_act') or '-'}"
                f"\n  ending     : {line.get('ending_shape') or '-'}"
                f"\n  norm_hints : {(line.get('normalization_hints') or '-')[:60]}"
                f"\n  pron_hints : {(line.get('pronunciation_hints') or '-')[:60]}"
                f"\n  prompt     : {instructions[:120]!r}{'…' if len(instructions) > 120 else ''}"
            )
            generate_tts_file(voice_id, line["text"], instructions, audio_path, intensity=line.get("intensity", 2), line=line)
            audio_map[str(idx)] = audio_url(audio_path)
        except Exception as e:
            print(f"[경고] line {idx} 음성 생성 실패: {e}")

    return json_response({
        "session_id": session_id,
        "audio_map": audio_map,
        "total_lines": len(req.lines),
        "user_character": req.user_character,
    })


@router.post("/generate-line")
async def generate_single_line(req: SingleLineRequest):
    char = req.character or "char"
    audio_path = single_line_audio_path(req.session_id, req.line_index, char, req.text)

    if not audio_path.exists():
        try:
            if TTS_PROVIDER == "elevenlabs":
                instructions = build_elevenlabs_prompt(
                    char_desc=req.character_description,
                    beat_goal=req.beat_goal,
                    subtext=req.subtext,
                    tts_direction=req.tts_direction,
                    emotion_label=req.emotion_label,
                    intensity=req.intensity,
                    speech_act=req.speech_act,
                    listener_pressure=req.listener_pressure,
                    phrase_breaks=req.phrase_breaks,
                    ending_shape=req.ending_shape,
                    delivery_mode=req.delivery_mode,
                    avoid=req.avoid,
                    next_cue_delay_ms=req.next_cue_delay_ms,
                )
            else:
                instructions = build_tts_instructions(
                    char_desc=req.character_description,
                    emotion_label=req.emotion_label,
                    intensity=req.intensity,
                    tempo=req.tempo,
                    beat_goal=req.beat_goal,
                    tactics=req.tactics,
                    subtext=req.subtext,
                    tts_direction=req.tts_direction,
                    emotion=req.emotion,
                )
            line_hints = {
                "pronunciation_hints": req.pronunciation_hints,
                "normalization_hints": req.normalization_hints,
            }
            generate_tts_file(req.voice_id, req.text, instructions, audio_path, intensity=req.intensity or 2, line=line_hints)
        except Exception as e:
            raise HTTPException(500, f"음성 생성 실패: {e}")

    return {"audio_url": audio_url(audio_path)}


@router.get("/check-elevenlabs")
async def check_elevenlabs():
    """ElevenLabs API key 설정 및 인증 상태 확인 (개발용)."""
    result = check_elevenlabs_auth()
    return json_response({"provider": "elevenlabs", **result})


@router.delete("/session/{session_id}")
async def cleanup_session(session_id: str):
    delete_session_files(session_id)
    return json_response({"message": "세션 삭제 완료"})
