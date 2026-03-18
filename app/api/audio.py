"""오디오 생성 엔드포인트.

POST /api/generate-rehearsal  — 전체 대본 AI 줄 일괄 생성
POST /api/generate-line       — 단일 줄 생성 (미리듣기 포함)
DELETE /api/session/{id}      — 세션 파일 정리
"""

import shutil
import uuid

from fastapi import APIRouter, HTTPException

from app.core.config import client
from app.schemas.requests import GenerateRehearsalRequest, SingleLineRequest
from app.utils.audio_paths import audio_url, rehearsal_audio_path, single_line_audio_path
from app.utils.instructions import build_tts_instructions
from app.utils.response import json_response

router = APIRouter()


@router.post("/generate-rehearsal")
async def generate_rehearsal(req: GenerateRehearsalRequest):
    session_id = req.session_id or str(uuid.uuid4())
    audio_map: dict = {}

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
            instructions = build_tts_instructions(
                char_desc=req.character_descriptions.get(char),
                emotion_label=line.get("emotion_label"),
                intensity=line.get("intensity"),
                tempo=line.get("tempo"),
                subtext=line.get("subtext"),
                tts_direction=line.get("tts_direction"),
                emotion=line.get("emotion"),
            )
            # 디버깅: 어떤 instruction이 어느 캐릭터/voice에 전달됐는지 확인
            print(f"[TTS] idx={idx} char={char!r} voice={voice_id} intensity={line.get('intensity')}")
            print(f"  >> {instructions!r}")
            tts_response = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=voice_id,
                input=line["text"],
                instructions=instructions,
                response_format="mp3",
            )
            tts_response.stream_to_file(str(audio_path))
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
            instructions = build_tts_instructions(
                char_desc=req.character_description,
                emotion_label=req.emotion_label,
                intensity=req.intensity,
                tempo=req.tempo,
                subtext=req.subtext,
                tts_direction=req.tts_direction,
                emotion=req.emotion,
            )
            tts_response = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=req.voice_id,
                input=req.text,
                instructions=instructions,
                response_format="mp3",
            )
            tts_response.stream_to_file(str(audio_path))
        except Exception as e:
            raise HTTPException(500, f"음성 생성 실패: {e}")

    return {"audio_url": audio_url(audio_path)}


@router.delete("/session/{session_id}")
async def cleanup_session(session_id: str):
    from app.core.config import AUDIO_DIR
    session_dir = AUDIO_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
    return json_response({"message": "세션 삭제 완료"})
