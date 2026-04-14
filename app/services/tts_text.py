"""TTS 텍스트 전처리 — 순수 함수, 외부 API 호출 없음.

format_text_for_elevenlabs — ElevenLabs 전용 텍스트 포맷팅
_normalize_tts_text        — pause 신호 변환 + 연기 지문 제거 (OpenAI 경로)
build_tts_input            — 양쪽 provider 공통 입력 조립
"""

import re
from dataclasses import dataclass


@dataclass
class TtsInput:
    cleaned_text: str
    instructions: str
    intensity: int
    speech_mode: str = "neutral"  # restrained | neutral | pressing | hesitant | cutting


def _parse_hint_rules(hints: str) -> list[tuple[str, str]]:
    """hints 문자열에서 (원문, 치환형) 쌍 목록을 파싱한다.

    지원 형식: "원문 → '변환형'" — 따옴표는 선택적, " / " 또는 줄바꿈으로 구분.
    예: "2014년 → '이천십사 년'" / "3% → '삼 퍼센트'" / "Dr. → '닥터'"
    """
    rules: list[tuple[str, str]] = []
    for seg in re.split(r"\s*/\s*|\n", hints):
        seg = seg.strip().strip("\"'")
        if "→" not in seg:
            continue
        src_raw, _, dst_raw = seg.partition("→")
        src = src_raw.strip().strip("\"'")
        dst = dst_raw.strip().strip("\"'「」\u201c\u201d\u2018\u2019")
        dst = re.sub(r"\s*(?:로|으로)(?:\s+읽기)?$", "", dst).strip()
        if src and dst and src != dst:
            rules.append((src, dst))
    return rules


def format_text_for_elevenlabs(text: str, line: dict | None = None) -> str:
    """ElevenLabs 전용 텍스트 포맷팅. _normalize_tts_text 실행 전에 적용한다.

    1. Korean pause markers → ElevenLabs가 인식하는 자연 구두점
         (사이)/(pause)/(beat) → ','  (짧은 쉼)
         (잠시)/(뜸)/(멈춤)   → '...' (긴 쉼)
    2. normalization_hints — 숫자/약어/외래어 → 읽기형 치환
    3. pronunciation_hints — 발음 주의 단어 → 표기형 치환
    """
    text = re.sub(r"\((?:사이|pause|beat)\)", ",", text)
    text = re.sub(r"\((?:잠시|뜸|멈춤)\)", "...", text)

    if line:
        norm = line.get("normalization_hints") or ""
        if isinstance(norm, str) and norm.strip():
            for src, dst in _parse_hint_rules(norm):
                text = text.replace(src, dst)

        pron = line.get("pronunciation_hints") or ""
        if isinstance(pron, str) and pron.strip():
            for src, dst in _parse_hint_rules(pron):
                text = text.replace(src, dst)

    return re.sub(r"\s{2,}", " ", text).strip()


def _normalize_tts_text(text: str) -> str:
    """TTS 텍스트 보존형 정규화.

    pause 신호 변환 (삭제가 아닌 변환):
      (사이)/(pause)/(beat) → '...' — OpenAI path용; ElevenLabs는 format_text_for_elevenlabs()가 먼저 처리
      (잠시)/(뜸)/(멈춤)    → '...'
    그 외 연기 지문 제거: (웃으며), (멈추고) 등
    보존: ..., …, — (자연 포즈 / cut-off 신호)
    정규화: -- → —, !{2,} → !
    """
    text = re.sub(r'\((?:사이|pause|beat)\)', '...', text)
    text = re.sub(r'\((?:잠시|뜸|멈춤)\)', '...', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = text.replace('--', '—')
    text = re.sub(r'!{2,}', '!', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _infer_speech_mode(instructions: str) -> str:
    """instructions 키워드로 speech mode 추론. 없으면 'neutral'."""
    if not instructions:
        return "neutral"
    t = instructions.lower()
    if any(k in t for k in ("절제", "억눌", "참으며", "조용히", "낮게", "속삭")):
        return "restrained"
    if any(k in t for k in ("압박", "몰아", "밀어", "추궁", "강하게")):
        return "pressing"
    if any(k in t for k in ("망설", "머뭇", "뜸들", "hesitant")):
        return "hesitant"
    if any(k in t for k in ("끊", "자르", "단호", "cutting")):
        return "cutting"
    return "neutral"


def build_tts_input(text: str, instructions: str, intensity: int = 2) -> TtsInput:
    """provider 호출 전 TTS 입력 정규화 및 조립.

    - cleaned_text: _normalize_tts_text() 적용 (양쪽 provider 공통)
    - instructions: strip + 연속 빈 줄 제거
    - intensity: 그대로 전달
    - speech_mode: instructions 키워드로 추론 (없으면 neutral)
    """
    cleaned = _normalize_tts_text(text)
    clean_instr = "\n".join(
        line for line in (instructions or "").strip().splitlines()
        if line.strip()
    )
    speech_mode = _infer_speech_mode(clean_instr)
    return TtsInput(cleaned_text=cleaned, instructions=clean_instr, intensity=intensity, speech_mode=speech_mode)
