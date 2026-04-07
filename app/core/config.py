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
# .env 또는 환경변수에서 "openai" | "elevenlabs" 선택 (기본: elevenlabs)
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "elevenlabs")

# ─── OpenAI 클라이언트 ──────────────────────────────────────────
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ─── 단계별 GPT 모델 라우팅 ────────────────────────────────────
# parse (text/chunk): 구조화만 — 빠르고 저렴한 모델
OPENAI_PARSE_FAST_MODEL   = os.environ.get("OPENAI_PARSE_FAST_MODEL",   "gpt-5.4-mini")
# parse (PDF direct, Responses API): vision + 대용량 컨텍스트
OPENAI_PARSE_PDF_MODEL    = os.environ.get("OPENAI_PARSE_PDF_MODEL",    "gpt-5.4")
# enrich_meta: 관계/심리 해석 — 품질 우선
OPENAI_ENRICH_MODEL       = os.environ.get("OPENAI_ENRICH_MODEL",       "gpt-5.4")
# voice assignment: 목소리 매칭 — 비교적 단순
OPENAI_VOICE_ASSIGN_MODEL = os.environ.get("OPENAI_VOICE_ASSIGN_MODEL", "gpt-5.4-mini")

# ─── ElevenLabs 설정 ───────────────────────────────────────────
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# ─── CORS 허용 origin ──────────────────────────────────────────
# ALLOWED_ORIGINS="https://example.com,http://localhost:3000" 형식으로 설정
# 값이 없으면 로컬 개발 전용 (localhost:8000만 허용) — 운영에서는 반드시 명시
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins.strip()
    else ["http://localhost:8000", "http://127.0.0.1:8000"]
)

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
    # 이 계정(free tier)에서 실제 접근 가능한 premade voices만 포함
    # 각 description: 성별 | 연령대 | 발화 질감 | 리허설 적합 캐릭터 유형
    {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "George",  "gender": "남성", "description": "남성, 중년, 따뜻하고 안정적인 스토리텔러형, 권위 있거나 침착한 캐릭터에 적합"},
    {"voice_id": "nPczCjzI2devNBz1zQrb", "name": "Brian",   "gender": "남성", "description": "남성, 중년, 깊고 안정적인 울림, 믿음직하고 무게감 있는 캐릭터에 적합"},
    {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",    "gender": "남성", "description": "남성, 중년 이상, 지배적이고 단호함, 강압적이거나 권위적인 캐릭터에 적합"},
    {"voice_id": "IKne3meq5aSn9XLyUdCD", "name": "Charlie", "gender": "남성", "description": "남성, 젊은 성인, 깊고 자신감 있으며 에너지 넘침, 적극적이고 열정적인 캐릭터에 적합"},
    {"voice_id": "TX3LPaxmHKxFdv7VOQHJ", "name": "Liam",    "gender": "남성", "description": "남성, 20대, 사교적이고 에너지 넘침, 충동적이거나 친근한 캐릭터에 적합"},
    {"voice_id": "CwhRBWXzGAHq8TQ4Fs17", "name": "Roger",   "gender": "남성", "description": "남성, 중년, 여유롭고 캐주얼, 느긋하거나 관찰자적인 캐릭터에 적합"},
    {"voice_id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel",  "gender": "남성", "description": "남성, 중년, 안정적이고 명확한 전달, 중립적이거나 직업적인 캐릭터에 적합"},
    {"voice_id": "iP95p4xoKVk53GoZ742B", "name": "Chris",   "gender": "남성", "description": "남성, 성인, 매력적이고 현실적, 공감 능력 있는 평범한 캐릭터에 적합"},
    {"voice_id": "pqHfZKP75CvOlQylNhV4", "name": "Bill",    "gender": "남성", "description": "남성, 중년 이상, 지혜롭고 균형 잡힌 성숙함, 인생 경험이 있는 연장자 캐릭터에 적합"},
    {"voice_id": "cgSgspJ2msm6clMCkdW9", "name": "Jessica", "gender": "여성", "description": "여성, 젊은 성인, 발랄하고 따뜻함, 친근하거나 감정이 직접적인 캐릭터에 적합"},
    {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah",   "gender": "여성", "description": "여성, 성인, 성숙하고 자신감 있으며 안정적, 주도적이거나 절제된 캐릭터에 적합"},
    {"voice_id": "Xb7hH8MSUJpSbSDYk0k2", "name": "Alice",   "gender": "여성", "description": "여성, 성인, 명확하고 지적이며 설득력 있음, 냉정하거나 분석적인 캐릭터에 적합"},
    {"voice_id": "XrExE9yKIg1WjnnlVkGX", "name": "Matilda", "gender": "여성", "description": "여성, 성인, 전문적이고 지식 있음, 신뢰감 있거나 권위적인 여성 캐릭터에 적합"},
    {"voice_id": "FGY2WhTYpPnrIDTdsKH5", "name": "Laura",   "gender": "여성", "description": "여성, 젊은 성인, 열정적이고 독특한 개성, 에너지 넘치거나 개성 강한 캐릭터에 적합"},
    {"voice_id": "pFZP5JQG7iQjIQuC4Bku", "name": "Lily",    "gender": "여성", "description": "여성, 성인, 부드럽고 연기적인 표현력, 감성적이거나 내면이 복잡한 캐릭터에 적합"},
    {"voice_id": "SAz9YHcvj6GT2YYXdXww", "name": "River",   "gender": "중성", "description": "중성, 성인, 편안하고 중립적이며 정보 전달에 최적, 관찰자나 해설자 역할에 적합"},
    {"voice_id": "hpp4J3VqNfWAUOO0d1Us", "name": "Bella",   "gender": "여성", "description": "여성, 성인, 전문적이고 밝으며 따뜻함, 사교적이거나 진취적인 캐릭터에 적합"},
    {"voice_id": "bIHbv24MWmeRgasZH58o", "name": "Will",    "gender": "남성", "description": "남성, 젊은 성인, 여유롭고 낙관적, 유연하거나 긍정적인 캐릭터에 적합"},
    {"voice_id": "cjVigY5qzO86Huf0OWal", "name": "Eric",    "gender": "남성", "description": "남성, 성인, 부드럽고 신뢰감 있음, 조용하거나 내향적인 캐릭터에 적합"},
    {"voice_id": "N2lVS1w4EtoT3dr4eOWO", "name": "Callum",  "gender": "남성", "description": "남성, 젊은 성인, 허스키하고 반항적, 불안정하거나 트릭스터 캐릭터에 적합"},
    {"voice_id": "SOYHLrjzK2X1ezoPC6cr", "name": "Harry",   "gender": "남성", "description": "남성, 젊은 성인, 강렬하고 전투적, 격렬하거나 대립적인 캐릭터에 적합"},
]

# ─── provider에 따른 활성 voice 목록 ───────────────────────────
TTS_VOICES = ELEVENLABS_TTS_VOICES if TTS_PROVIDER == "elevenlabs" else OPENAI_TTS_VOICES
VALID_VOICE_IDS: set[str] = {v["voice_id"] for v in TTS_VOICES}
