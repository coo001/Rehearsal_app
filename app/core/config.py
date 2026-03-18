import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ─── 경로 설정 ──────────────────────────────────────────────────
AUDIO_DIR = Path("audio")
AUDIO_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("static")

# ─── OpenAI 클라이언트 ──────────────────────────────────────────
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ─── TTS 목소리 목록 (11종) ──────────────────────────────────────
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

VALID_VOICE_IDS: set[str] = {v["voice_id"] for v in TTS_VOICES}
