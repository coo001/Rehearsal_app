import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ─── 경로 설정 ──────────────────────────────────────────────────
AUDIO_DIR = Path("audio")
AUDIO_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("static")

# ─── TTS provider 설정 ─────────────────────────────────────────
# .env 또는 환경변수에서 "openai" | "elevenlabs" 선택 (기본: openai)
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "openai")

# ─── OpenAI 클라이언트 ──────────────────────────────────────────
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ─── ElevenLabs 설정 ───────────────────────────────────────────
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# ─── OpenAI TTS 목소리 목록 (11종) ─────────────────────────────
OPENAI_TTS_VOICES = [
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

# ─── ElevenLabs TTS 목소리 목록 ────────────────────────────────
ELEVENLABS_TTS_VOICES = [
    # 각 description: 성별 | 연령대 | 발화 질감 | 리허설 적합 캐릭터 유형
    {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "George",  "gender": "남성", "description": "남성, 중년, 낮고 절제된 대화형, 권위 있거나 침착한 캐릭터에 적합"},
    {"voice_id": "nPczCjzI2devNBz1zQrb", "name": "Brian",   "gender": "남성", "description": "남성, 젊은 중년, 차분하고 자연스러운 대화형, 평범하고 현실적인 캐릭터에 적합"},
    {"voice_id": "cgSgspJ2msm6clMCkdW9", "name": "Jessica", "gender": "여성", "description": "여성, 젊은 성인, 따뜻하고 자연스러운 대화형, 친근하거나 감정이 풍부한 캐릭터에 적합"},
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella",   "gender": "여성", "description": "여성, 젊은 성인, 부드럽고 감성적, 내향적이거나 조용한 캐릭터에 적합"},
    {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",    "gender": "남성", "description": "남성, 중년 이상, 깊고 무게감 있음, 성숙하거나 권위적인 캐릭터에 적합"},
    {"voice_id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam",     "gender": "중성", "description": "중성, 젊은 성인, 명확하고 안정적인 전달, 중립적이거나 직업적인 캐릭터에 적합"},
    {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",  "gender": "여성", "description": "여성, 성인, 차분하고 지적, 냉정하거나 절제된 캐릭터에 적합"},
    {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli",    "gender": "여성", "description": "여성, 10대~20대 초반, 밝고 에너지 넘침, 젊고 감정이 직접적인 캐릭터에 적합"},
    {"voice_id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh",    "gender": "남성", "description": "남성, 20대, 젊고 다이나믹, 충동적이거나 열정적인 캐릭터에 적합"},
    {"voice_id": "VR6AewLTigWG4xSOukaG", "name": "Arnold",  "gender": "남성", "description": "남성, 중년 이상, 강하고 단호함, 지배적이거나 갈등을 주도하는 캐릭터에 적합"},
    {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi",    "gender": "여성", "description": "여성, 성인, 강하고 직접적, 자기주장이 강하거나 공격적인 캐릭터에 적합"},
]

# ─── provider에 따른 활성 voice 목록 ───────────────────────────
TTS_VOICES = ELEVENLABS_TTS_VOICES if TTS_PROVIDER == "elevenlabs" else OPENAI_TTS_VOICES
VALID_VOICE_IDS: set[str] = {v["voice_id"] for v in TTS_VOICES}
