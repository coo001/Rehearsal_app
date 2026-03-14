"""
대본 연습 시스템 - OpenAI 전용
GPT-4o: 대본 파싱 & 캐릭터 분석
OpenAI TTS: 음성 생성 (alloy / echo / fable / onyx / nova / shimmer)
"""

import os
import json
import uuid
from pathlib import Path
from typing import Optional

from openai import OpenAI
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="대본 연습 시스템")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = Path("audio")
AUDIO_DIR.mkdir(exist_ok=True)

app.mount("/audio", StaticFiles(directory="audio"), name="audio")
app.mount("/static", StaticFiles(directory="static"), name="static")

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# OpenAI TTS에서 사용 가능한 목소리
TTS_VOICES = [
    {"voice_id": "alloy",   "name": "Alloy",   "description": "중성적, 부드러움"},
    {"voice_id": "echo",    "name": "Echo",    "description": "남성적, 차분함"},
    {"voice_id": "fable",   "name": "Fable",   "description": "영국식, 따뜻함"},
    {"voice_id": "onyx",    "name": "Onyx",    "description": "남성적, 깊고 중후함"},
    {"voice_id": "nova",    "name": "Nova",    "description": "여성적, 활기참"},
    {"voice_id": "shimmer", "name": "Shimmer", "description": "여성적, 부드러움"},
]


# ─── 요청 모델 ────────────────────────────────────────────────
class ParseScriptRequest(BaseModel):
    script: str

class GenerateRehearsalRequest(BaseModel):
    lines: list
    voice_assignments: dict   # {"캐릭터명": "voice_id"}
    user_character: str
    session_id: Optional[str] = None

class SingleLineRequest(BaseModel):
    text: str
    voice_id: str
    session_id: str
    line_index: int


# ─── 대본 파싱 (GPT-4o) ───────────────────────────────────────
PARSE_SYSTEM_PROMPT = """당신은 대본 분석 전문가입니다. 주어진 대본을 분석하여 구조화된 JSON으로 반환하세요.

반환 형식:
{
  "title": "작품 제목 (없으면 '제목 없음')",
  "characters": ["캐릭터1", "캐릭터2"],
  "character_descriptions": {
    "캐릭터1": "성격, 역할, 특징 간략 설명 (2-3문장)",
    "캐릭터2": "..."
  },
  "lines": [
    {"type": "dialogue", "character": "캐릭터명", "text": "대사 내용"},
    {"type": "direction", "text": "지문/무대지시 내용"}
  ]
}

규칙:
- 대사: type = "dialogue", 지문/무대지시: type = "direction"
- characters는 실제 대사가 있는 인물만 포함
- 캐릭터명은 대본에 나온 그대로 유지
- JSON 외 다른 텍스트 절대 포함 금지
- 반드시 유효한 JSON만 반환"""


@app.post("/api/parse-script")
async def parse_script(req: ParseScriptRequest):
    if not req.script.strip():
        raise HTTPException(400, "대본 내용을 입력해주세요.")

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": f"다음 대본을 분석해주세요:\n\n{req.script}"}
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
        data = json.loads(text)
        return JSONResponse(data)

    except json.JSONDecodeError as e:
        raise HTTPException(500, f"대본 파싱 실패 (JSON 오류): {e}")
    except Exception as e:
        raise HTTPException(500, f"대본 파싱 중 오류: {e}")


# ─── 목소리 목록 ──────────────────────────────────────────────
@app.get("/api/voices")
async def get_voices():
    return {"voices": TTS_VOICES}


# ─── 음성 일괄 생성 (OpenAI TTS) ─────────────────────────────
@app.post("/api/generate-rehearsal")
async def generate_rehearsal(req: GenerateRehearsalRequest):
    session_id = req.session_id or str(uuid.uuid4())
    session_dir = AUDIO_DIR / session_id
    session_dir.mkdir(exist_ok=True)

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

        audio_path = session_dir / f"line_{idx}.mp3"
        if audio_path.exists():
            audio_map[str(idx)] = f"/audio/{session_id}/line_{idx}.mp3"
            continue

        try:
            tts_response = client.audio.speech.create(
                model="tts-1",
                voice=voice_id,
                input=line["text"],
                response_format="mp3",
            )
            tts_response.stream_to_file(str(audio_path))
            audio_map[str(idx)] = f"/audio/{session_id}/line_{idx}.mp3"
        except Exception as e:
            print(f"[경고] line_{idx} 음성 생성 실패: {e}")

    return {
        "session_id": session_id,
        "audio_map": audio_map,
        "total_lines": len(req.lines),
        "user_character": req.user_character,
    }


# ─── 단일 줄 음성 생성 ────────────────────────────────────────
@app.post("/api/generate-line")
async def generate_single_line(req: SingleLineRequest):
    session_dir = AUDIO_DIR / req.session_id
    session_dir.mkdir(exist_ok=True)
    audio_path = session_dir / f"line_{req.line_index}.mp3"

    if not audio_path.exists():
        try:
            tts_response = client.audio.speech.create(
                model="tts-1",
                voice=req.voice_id,
                input=req.text,
                response_format="mp3",
            )
            tts_response.stream_to_file(str(audio_path))
        except Exception as e:
            raise HTTPException(500, f"음성 생성 실패: {e}")

    return {"audio_url": f"/audio/{req.session_id}/line_{req.line_index}.mp3"}


# ─── 세션 정리 ─────────────────────────────────────────────────
@app.delete("/api/session/{session_id}")
async def cleanup_session(session_id: str):
    import shutil
    session_dir = AUDIO_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
    return {"message": "세션 삭제 완료"}


# ─── 루트 ─────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
