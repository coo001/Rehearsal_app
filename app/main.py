"""FastAPI 앱 부트스트랩.

미들웨어, 예외 핸들러, 정적 파일 마운트, 라우터 등록을 모두 여기서 처리한다.
"""

import json
import logging
import sys

# Windows cp949 stdout/stderr 에서 em-dash(U+2014) 등 비-cp949 문자 출력 시
# UnicodeEncodeError가 발생하는 문제를 방지한다.
# errors='replace' → 인코딩 불가 문자는 '?'로 치환, 프로세스가 죽지 않음.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.core.logging_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import audio, script, sessions, voices
from app.core.config import AUDIO_DIR, ALLOWED_ORIGINS, TTS_PROVIDER

app = FastAPI(title="대본 연습 시스템")

# ─── CORS ──────────────────────────────────────────────────────
# 허용 origin은 환경변수 ALLOWED_ORIGINS(콤마 구분)로 설정.
# 미설정 시 localhost:8000만 허용 — 운영 배포 전 반드시 ALLOWED_ORIGINS 지정.
logger.info("[CORS] allowed_origins=%s", ALLOWED_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 보안 헤더 ────────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ─── 한국어 에러 메시지 Content-Length 오류 방지 ──────────────────
@app.exception_handler(HTTPException)
async def korean_http_exception_handler(request: Request, exc: HTTPException):
    body = json.dumps({"detail": exc.detail}, ensure_ascii=False).encode("utf-8")
    return Response(content=body, status_code=exc.status_code, media_type="application/json")

# ─── 정적 파일 마운트 ───────────────────────────────────────────
app.mount("/audio",  StaticFiles(directory=str(AUDIO_DIR)), name="audio")
app.mount("/static", StaticFiles(directory="static"),       name="static")

# ─── API 라우터 ─────────────────────────────────────────────────
app.include_router(script.router,   prefix="/api")
app.include_router(voices.router,   prefix="/api")
app.include_router(audio.router,    prefix="/api")
app.include_router(sessions.router, prefix="/api")


# ─── 루트 & 파비콘 ──────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health():
    return JSONResponse({"ok": True})


# ─── Startup summary ────────────────────────────────────────────
@app.on_event("startup")
async def startup_summary():
    logger.info(
        "[Startup] tts_provider=%s | cors=%s | audio_mount=%s | static_mount=static",
        TTS_PROVIDER, ALLOWED_ORIGINS, AUDIO_DIR,
    )
