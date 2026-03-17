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
    character_description: Optional[str] = None
    # 신규 구조화 필드
    emotion_label: Optional[str] = None
    intensity: Optional[int] = None
    tempo: Optional[str] = None
    subtext: Optional[str] = None
    tts_direction: Optional[str] = None
    # 하위 호환
    emotion: Optional[str] = None

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
def _build_instructions(
    char_desc: str | None,
    emotion_label: str | None = None,
    intensity: int | None = None,       # 1(절제) ~ 5(강렬)
    tempo: str | None = None,           # "느리게" | "보통" | "빠르게"
    subtext: str | None = None,
    tts_direction: str | None = None,
    # 하위 호환: 구형 단일 emotion 문자열
    emotion: str | None = None,
) -> str:
    parts = [
        "당신은 배우와 함께 장면을 연습하는 상대 배우입니다.",
        "대사를 자연스럽고 인간적으로 말하세요.",
        "감정은 억지로 강조하지 말고, 장면이 요구할 때만 드러내세요.",
        "과도한 강세, 과장된 호흡, 선언하듯 읽는 말투는 피하세요.",
        "일상 대화처럼 자연스럽게 시작하되, 감정이 있다면 절제된 방식으로 표현하세요.",
    ]
    if char_desc:
        parts.append(f"캐릭터: {char_desc}")

    # 구형 단일 emotion 필드 폴백
    if emotion and not emotion_label:
        parts.append(f"감정 참고: {emotion} — 과장하지 말고 자연스럽게.")
    else:
        if emotion_label:
            parts.append(f"감정: {emotion_label}")
        if intensity is not None:
            level = ["매우 절제", "차분", "보통", "다소 강하게", "강렬하게"][max(0, min(4, intensity - 1))]
            parts.append(f"강도: {level} (1~5 중 {intensity})")
        if tempo:
            parts.append(f"속도: {tempo}")
        if subtext:
            parts.append(f"내면: {subtext} — 이 감정은 겉으로 드러내기보다 목소리 안에 담으세요.")
        if tts_direction:
            parts.append(f"발화 방식: {tts_direction}")

    return " | ".join(parts)


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
      "emotion_label": "감정을 단어 하나 또는 짧은 구로 (예: 분노, 슬픔, 불안, 무기력, 비꼼, 애정, 당혹)",
      "intensity": 2,
      "tempo": "보통",
      "subtext": "이 대사 이면의 실제 의도나 억눌린 감정 (1문장, 없으면 null)",
      "tts_direction": "발화 방식 지시 — 짧고 실용적으로 (예: '낮고 건조하게, 끝을 흐리며' / '빠르게, 끊어서'). 과장 금지.",
      "pause_after": 600
    },
    {"type": "direction", "text": "지문/무대지시 내용"}
  ]
}

intensity 기준 (정수 1~5):
1 = 매우 절제 (평온, 무감각, 숨김)
2 = 차분 (기본 대화, 억제된 감정)
3 = 보통 (감정이 자연스럽게 드러남)
4 = 다소 강함 (감정이 표면에 올라옴)
5 = 강렬 (폭발, 절규, 극적 전환점 — 장면 전체에서 드물게)

tempo: "느리게" | "보통" | "빠르게"

pause_after 기준 (단위: 밀리초):
- 일반 대화 교환: 400~700
- 감정적 대사 후: 800~1500
- 충격적/극적 순간 후: 1500~3000
- 짧은 반응 대사: 300~500
- 지문 다음 첫 대사: 600~1000

규칙:
- 대사: type = "dialogue", 지문: type = "direction" (direction에는 감정 필드 없음)
- characters는 실제 대사가 있는 인물만, 캐릭터명은 대본 그대로
- intensity는 기본값 2로 시작하고, 명확한 근거가 있을 때만 높이세요
- tts_direction은 실용적인 발화 지시여야 하며, 문학적 묘사는 금지
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
아래 캐릭터 목록과 TTS 목소리 목록을 보고, 각 캐릭터에 가장 어울리는 목소리를 배정하세요.

목소리 목록:
{voices_info}

캐릭터 정보:
{characters_info}

배정 기준 (우선순위 순):
1. 성별 및 나이대 일치
2. 캐릭터의 감정 에너지와 목소리 톤 매칭 (예: 차갑고 권위적인 캐릭터 → 낮고 중후한 목소리)
3. 장면 내 캐릭터 간 대비 — 비슷한 목소리가 겹치지 않도록 청각적으로 구분
4. 캐릭터의 사회적 위치, 분위기, 존재감

규칙:
- 각 캐릭터에 반드시 하나의 voice_id 배정
- 같은 목소리를 여러 캐릭터에 배정하지 마세요 (불가피한 경우 제외)
- 반환 형식 (JSON만, 다른 텍스트 금지):
{{
  "assignments": {{"캐릭터명": "voice_id"}},
  "reasons": {{"캐릭터명": "배정 이유 한 줄"}}
}}"""


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
        result = json.loads(response.choices[0].message.content)
        # 새 형식 {assignments: {...}, reasons: {...}} 또는 구형 {"캐릭터": "voice_id"} 모두 처리
        assignments = result.get("assignments", result)
        reasons = result.get("reasons", {})
        # 유효한 voice_id만 필터링
        valid_ids = {v["voice_id"] for v in TTS_VOICES}
        assignments = {k: v for k, v in assignments.items() if v in valid_ids}
        return _json({"assignments": assignments, "reasons": reasons})
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
                char_desc=req.character_descriptions.get(char),
                emotion_label=line.get("emotion_label"),
                intensity=line.get("intensity"),
                tempo=line.get("tempo"),
                subtext=line.get("subtext"),
                tts_direction=line.get("tts_direction"),
                emotion=line.get("emotion"),  # 구형 데이터 폴백
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
            instructions = _build_instructions(
                char_desc=req.character_description,
                emotion_label=req.emotion_label,
                intensity=req.intensity,
                tempo=req.tempo,
                subtext=req.subtext,
                tts_direction=req.tts_direction,
                emotion=req.emotion,  # 구형 클라이언트 폴백
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
