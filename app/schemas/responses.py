"""API 응답 Pydantic 모델.

런타임 직렬화 강제보다 OpenAPI 스키마 문서화가 주 목적이다.
엔드포인트가 json_response()를 사용하는 경우 FastAPI가 이 모델로
실제 검증을 수행하지는 않지만, response_model= 에 넣으면 Swagger 문서에
응답 구조가 표시된다.
"""

from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.requests import ScriptLine


# ── 공통 ─────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


# ── /api/voices ──────────────────────────────────────────────────

class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    gender: str
    description: str


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


# ── /api/auto-assign-voices ──────────────────────────────────────

class AutoAssignResponse(BaseModel):
    assignments: dict[str, str]


# ── /api/parse-script, /api/parse-pdf ────────────────────────────
# ParsedLine의 필드 구조는 ScriptLine(입력)과 동일하므로 재사용한다.
ParsedLine = ScriptLine


class ParsedScriptResponse(BaseModel):
    title: Optional[str] = None
    characters: list[str] = []
    character_descriptions: dict[str, str] = {}
    character_analysis: dict[str, Any] = {}
    relationships: dict[str, Any] = {}
    lines: list[ParsedLine] = []
    partial_failure: Optional[dict[str, Any]] = None


# ── /api/extract-pdf ─────────────────────────────────────────────

class ExtractPdfResponse(BaseModel):
    text: str
    char_count: int
    total_pages: int
    skipped_pages: list[int]


# ── /api/generate-rehearsal ──────────────────────────────────────

class GenerateRehearsalResponse(BaseModel):
    session_id: str
    audio_map: dict[str, str]    # {"line_index": "audio_url"}
    total_lines: int
    user_character: str


# ── /api/generate-line ───────────────────────────────────────────

class GenerateLineResponse(BaseModel):
    audio_url: str


# ── /api/check-elevenlabs ────────────────────────────────────────

class ElevenLabsCheckResponse(BaseModel):
    provider: str
    configured: bool
    auth_ok: bool
    detail: str


# ── /api/sessions ────────────────────────────────────────────────

class SessionSummary(BaseModel):
    session_id: str
    title: str
    updated_at: str
    user_character: str
    characters: list[str]
    audio_count: int


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class SessionDetailResponse(BaseModel):
    session_id: str
    title: Optional[str] = None
    updated_at: Optional[str] = None
    created_at: Optional[str] = None
    user_character: Optional[str] = None
    audio_map: dict[str, str] = {}
    parsed_script: Optional[ParsedScriptResponse] = None


class UpsertSessionResponse(BaseModel):
    session_id: str
