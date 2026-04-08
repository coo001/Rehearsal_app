"""Pydantic 요청 스키마."""

from typing import Optional

from pydantic import BaseModel


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
    character: Optional[str] = None           # 파일명 슬러그 생성용 (없으면 "char")
    character_description: Optional[str] = None
    # 구조화 감정 필드
    emotion_label: Optional[str] = None
    intensity: Optional[int] = None
    tempo: Optional[str] = None
    beat_goal: Optional[str] = None
    tactics: Optional[str] = None
    subtext: Optional[str] = None
    tts_direction: Optional[str] = None
    # 발화 행동·호흡·끝처리 필드
    speech_act: Optional[str] = None
    listener_pressure: Optional[str] = None
    phrase_breaks: Optional[str] = None
    ending_shape: Optional[str] = None
    delivery_mode: Optional[str] = None
    avoid: Optional[str] = None
    # TTS 발음/정규화 힌트 (ElevenLabs 전용 텍스트 포맷팅에 사용)
    pronunciation_hints: Optional[str] = None
    normalization_hints: Optional[str] = None
    # timing (ElevenLabs hesitation cue 및 playback scheduler용)
    next_cue_delay_ms: Optional[int] = None
    # 하위 호환: 구형 단일 emotion 문자열
    emotion: Optional[str] = None


class AutoAssignRequest(BaseModel):
    characters: list                 # AI 음성이 필요한 캐릭터 목록
    character_descriptions: dict     # {"캐릭터명": "설명"}
    user_preferences: Optional[dict] = None  # {"캐릭터명": "더 차분하게"} — 없으면 기본 배정
