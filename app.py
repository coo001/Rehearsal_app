"""
대본 연습 시스템 - OpenAI 전용
GPT-4o: 대본 파싱 & 캐릭터 분석 & 감정/타이밍 분석 & 자동 목소리 배정
gpt-4o-mini-tts: 감정 연기 음성 생성
"""

import os
import json
import uuid
from pathlib import Path
from typing import Optional

from openai import OpenAI
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.exception_handlers import http_exception_handler as _default_http_handler
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

# ─── 한국어 에러 메시지 Content-Length 오류 방지 ──────────────
@app.exception_handler(HTTPException)
async def korean_http_exception_handler(request: Request, exc: HTTPException):
    body = json.dumps({"detail": exc.detail}, ensure_ascii=False).encode("utf-8")
    return Response(content=body, status_code=exc.status_code, media_type="application/json")

AUDIO_DIR = Path("audio")
AUDIO_DIR.mkdir(exist_ok=True)

app.mount("/audio", StaticFiles(directory="audio"), name="audio")
app.mount("/static", StaticFiles(directory="static"), name="static")

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# OpenAI TTS 전체 목소리 목록 (11종) + 성별/특징 메타데이터
TTS_VOICES = [
    {"voice_id": "alloy",   "name": "Alloy",   "gender": "중성", "description": "중성적, 차분하고 안정적"},
    {"voice_id": "ash",     "name": "Ash",     "gender": "남성", "description": "남성적, 젊고 에너지 넘침"},
    {"voice_id": "ballad",  "name": "Ballad",  "gender": "남성", "description": "남성적, 감성적이고 서정적"},
    {"voice_id": "coral",   "name": "Coral",   "gender": "여성", "description": "여성적, 따뜻하고 친근함"},
    {"voice_id": "echo",    "name": "Echo",    "gender": "남성", "description": "남성적, 깊고 차분함"},
    {"voice_id": "fable",   "name": "Fable",   "gender": "중성", "description": "중성적, 영국식 억양, 표현력 풍부"},
    {"voice_id": "nova",    "name": "Nova",    "gender": "여성", "description": "여성적, 활기차고 젊음"},
    {"voice_id": "onyx",    "name": "Onyx",    "gender": "남성", "description": "남성적, 깊고 중후한 베이스"},
    {"voice_id": "sage",    "name": "Sage",    "gender": "남성", "description": "남성적, 성숙하고 지혜로운"},
    {"voice_id": "shimmer", "name": "Shimmer", "gender": "여성", "description": "여성적, 부드럽고 우아함"},
    {"voice_id": "verse",   "name": "Verse",   "gender": "중성", "description": "중성적, 극적 표현력이 가장 강함"},
]


# ─── 요청 모델 ────────────────────────────────────────────────
class ParseScriptRequest(BaseModel):
    script: str

class GenerateRehearsalRequest(BaseModel):
    lines: list
    voice_assignments: dict          # {"캐릭터명": "voice_id"}
    user_character: str
    character_descriptions: dict     # {"캐릭터명": "성격 설명"}
    session_id: Optional[str] = None

class SingleLineRequest(BaseModel):
    text: str
    voice_id: str
    session_id: str
    line_index: int
    emotion: Optional[str] = None
    character_description: Optional[str] = None

class AutoAssignRequest(BaseModel):
    characters: list                 # AI 음성이 필요한 캐릭터 목록
    character_descriptions: dict     # {"캐릭터명": "설명"}


# ─── 한국어 안전 JSON 응답 ────────────────────────────────────
def _json(data):
    """bytes로 직접 전달 — 구버전 starlette의 Content-Length 오류 방지
    문자열을 넘기면 len(str)로 계산해 한국어(1자=3바이트)에서 불일치 발생"""
    body: bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(content=body, media_type="application/json")


# ─── TTS instructions 빌더 ───────────────────────────────────
def _build_instructions(char_desc: str | None, emotion: str | None) -> str:
    lines = [
        "당신은 연극 무대의 전문 성우입니다.",
        "대사를 읽는 것이 아니라 완전히 그 캐릭터가 되어 몰입해서 연기하세요.",
        "감정을 절대 억제하지 말고 최대한 강렬하고 생생하게 표현하세요.",
        "단조로운 TTS처럼 절대 들려선 안 됩니다. 목소리 높낮이·속도·감정 기복을 크게 주세요.",
        "실제 배우가 무대에서 연기하듯 극적으로 말하세요.",
    ]
    if char_desc:
        lines.append(f"캐릭터 특성: {char_desc}")
    if emotion:
        lines.append(
            f"이 대사의 감정·말투: {emotion} "
            f"— 이 감정을 극대화하여, 듣는 사람이 즉시 느낄 수 있도록 강하게 표현하세요."
        )
    return " ".join(lines)


# ─── 대본 파싱 (GPT-4o) ───────────────────────────────────────
PARSE_SYSTEM_PROMPT = """당신은 연극 대본 분석 전문가입니다. 주어진 대본을 분석하여 구조화된 JSON으로 반환하세요.

반환 형식:
{
  "title": "작품 제목 (없으면 '제목 없음')",
  "characters": ["캐릭터1", "캐릭터2"],
  "character_descriptions": {
    "캐릭터1": "성격, 역할, 특징 간략 설명 (2-3문장)",
    "캐릭터2": "..."
  },
  "lines": [
    {
      "type": "dialogue",
      "character": "캐릭터명",
      "text": "대사 내용",
      "emotion": "이 대사의 감정과 말투를 구체적으로 서술 (예: '분노로 이를 악물며 낮고 떨리는 목소리로', '눈물을 참으며 슬프게 속삭이듯', '흥분해서 빠르고 높은 톤으로')",
      "pause_after": 800
    },
    {"type": "direction", "text": "지문/무대지시 내용"}
  ]
}

pause_after 규칙 (단위: 밀리초):
- 일반 대화 교환: 400~700
- 감정적 대사 후: 800~1500
- 충격적/극적 순간 후: 1500~3000
- 짧은 반응 대사: 300~500
- 지문 다음 첫 대사 전: 600~1000

규칙:
- 대사: type = "dialogue", 지문: type = "direction" (direction에는 emotion/pause_after 없음)
- characters는 실제 대사가 있는 인물만
- 캐릭터명은 대본 그대로
- emotion은 배우 디렉션처럼 구체적으로 (감정 + 말투 + 신체 상태 포함)
- JSON 외 다른 텍스트 절대 금지"""


@app.post("/api/parse-script")
async def parse_script(req: ParseScriptRequest):
    if not req.script.strip():
        raise HTTPException(400, "대본 내용을 입력해주세요.")
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user",   "content": f"다음 대본을 분석해주세요:\n\n{req.script}"}
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return _json(data)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"대본 파싱 실패 (JSON 오류): {e}")
    except Exception as e:
        raise HTTPException(500, f"대본 파싱 중 오류: {e}")


# ─── 목소리 목록 ──────────────────────────────────────────────
@app.get("/api/voices")
async def get_voices():
    return _json({"voices": TTS_VOICES})


# ─── AI 자동 목소리 배정 ──────────────────────────────────────
AUTO_ASSIGN_PROMPT = """당신은 연극 음향 감독입니다.
아래 캐릭터 목록과 사용 가능한 TTS 목소리 목록을 보고,
각 캐릭터에 가장 어울리는 목소리를 배정하세요.

목소리 목록:
{voices_info}

캐릭터 정보:
{characters_info}

규칙:
- 각 캐릭터에 반드시 하나의 voice_id를 배정
- 같은 목소리를 여러 캐릭터에 배정하지 마세요 (캐릭터가 목소리 수보다 많으면 불가피한 경우 제외)
- 캐릭터의 성별, 나이, 성격을 목소리 특성과 최대한 매칭
- JSON만 반환: {{"캐릭터명": "voice_id", ...}}"""


@app.post("/api/auto-assign-voices")
async def auto_assign_voices(req: AutoAssignRequest):
    if not req.characters:
        return {"assignments": {}}

    voices_info = "\n".join(
        f"- {v['voice_id']}: {v['name']} | {v['gender']} | {v['description']}"
        for v in TTS_VOICES
    )
    characters_info = "\n".join(
        f"- {c}: {req.character_descriptions.get(c, '설명 없음')}"
        for c in req.characters
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": AUTO_ASSIGN_PROMPT.format(
                    voices_info=voices_info,
                    characters_info=characters_info,
                )},
                {"role": "user", "content": "각 캐릭터에 최적의 목소리를 배정해주세요."}
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        assignments = json.loads(response.choices[0].message.content)
        # 유효한 voice_id만 필터링
        valid_ids = {v["voice_id"] for v in TTS_VOICES}
        assignments = {k: v for k, v in assignments.items() if v in valid_ids}
        return _json({"assignments": assignments})
    except Exception as e:
        raise HTTPException(500, f"자동 배정 실패: {e}")


# ─── 음성 일괄 생성 ───────────────────────────────────────────
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
            instructions = _build_instructions(
                req.character_descriptions.get(char),
                line.get("emotion"),
            )
            tts_response = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=voice_id,
                input=line["text"],
                instructions=instructions,
                response_format="mp3",
            )
            tts_response.stream_to_file(str(audio_path))
            audio_map[str(idx)] = f"/audio/{session_id}/line_{idx}.mp3"
        except Exception as e:
            print(f"[경고] line_{idx} 음성 생성 실패: {e}")

    return _json({
        "session_id": session_id,
        "audio_map": audio_map,
        "total_lines": len(req.lines),
        "user_character": req.user_character,
    })


# ─── 단일 줄 음성 생성 ────────────────────────────────────────
@app.post("/api/generate-line")
async def generate_single_line(req: SingleLineRequest):
    session_dir = AUDIO_DIR / req.session_id
    session_dir.mkdir(exist_ok=True)
    audio_path = session_dir / f"line_{req.line_index}.mp3"

    if not audio_path.exists():
        try:
            instructions = _build_instructions(req.character_description, req.emotion)
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

    return {"audio_url": f"/audio/{req.session_id}/line_{req.line_index}.mp3"}


# ─── 세션 정리 ─────────────────────────────────────────────────
@app.delete("/api/session/{session_id}")
async def cleanup_session(session_id: str):
    import shutil
    session_dir = AUDIO_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
    return _json({"message": "세션 삭제 완료"})


# ─── 루트 ─────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/favicon.ico")
async def favicon():
    # JSONResponse(status_code=204, content=None)은 body="null"(4바이트)를 보내려다
    # uvicorn이 204는 body 없음을 강제해서 Content-Length 불일치 오류 발생
    return Response(status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
