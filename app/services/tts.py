"""TTS 음성 생성 및 세션 파일 관리."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import (
    AUDIO_DIR,
    ELEVENLABS_API_KEY,
    ELEVENLABS_MODEL_ID,
    TTS_PROVIDER,
    client,
)


def generate_tts_file(
    voice_id: str,
    text: str,
    instructions: str,
    audio_path: Path,
    intensity: int = 2,
    line: dict | None = None,
) -> None:
    """TTS_PROVIDER에 따라 OpenAI 또는 ElevenLabs로 음성 생성 후 mp3 저장."""
    if TTS_PROVIDER == "elevenlabs":
        text = format_text_for_elevenlabs(text, line)
    tts = build_tts_input(text, instructions, intensity)
    if TTS_PROVIDER == "elevenlabs":
        _generate_elevenlabs(voice_id, tts.cleaned_text, tts.instructions, audio_path, tts.intensity, tts.speech_mode)
    else:
        _generate_openai(voice_id, tts.cleaned_text, tts.instructions, audio_path)


def _log_tts_input(
    provider: str,
    voice_id: str,
    text: str,
    instructions: str,
    intensity: int | None = None,
    speech_mode: str | None = None,
    stability: float | None = None,
    style: float | None = None,
) -> None:
    """provider 호출 직전 TTS 입력 preview 로그. API key 등 민감값 제외."""
    print(
        f"[TTS] provider={provider} voice={voice_id}\n"
        f"  text        : {text[:80]!r}{'...' if len(text) > 80 else ''}\n"
        f"  instructions: {instructions[:120]!r}{'...' if len(instructions) > 120 else ''}\n"
        f"  intensity={intensity} mode={speech_mode} stability={stability} style={style}"
    )


def _generate_openai(voice_id: str, text: str, instructions: str, audio_path: Path) -> None:
    _log_tts_input("openai", voice_id, text, instructions)
    tts_response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice_id,
        input=text,
        instructions=instructions,
        response_format="mp3",
    )
    tts_response.stream_to_file(str(audio_path))


def _parse_hint_rules(hints: str) -> list[tuple[str, str]]:
    """hints 문자열에서 (원문, 치환형) 쌍 목록을 파싱한다.

    지원 형식: "원문 → '변환형'" — 따옴표는 선택적, " / " 또는 줄바꿈으로 구분.
    예: "2014년 → '이천십사 년'" / "3% → '삼 퍼센트'" / "Dr. → '닥터'"
    """
    import re
    rules: list[tuple[str, str]] = []
    for seg in re.split(r"\s*/\s*|\n", hints):
        seg = seg.strip().strip("\"'")
        if "→" not in seg:
            continue
        src_raw, _, dst_raw = seg.partition("→")
        src = src_raw.strip().strip("\"'")
        dst = dst_raw.strip().strip("\"'「」""''")
        # trailing particles like "로", "으로 읽기" 제거
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
    import re
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

    제거: 일반 연기 지문 — (웃으며), (멈추고) 등
    보존: pause 신호 괄호 — (사이)/(잠시)/(뜸)/(pause)/(beat)/(멈춤)
          TTS가 자연 호흡으로 처리하도록 원문 유지
    보존: .../ … — TTS가 자연 포즈로 인식, 쉼표로 평탄화하지 않음
    보존: —    — cut-off/끊김 신호 유지
    정규화: -- → — (표기 통일, 의미 보존)
    제거: !{2,} → ! (과장 억제)
    정리: 다중 공백
    """
    import re
    # pause 신호 괄호는 보존, 그 외 지문만 제거
    text = re.sub(r'\((?!사이|잠시|뜸|pause|beat|멈춤).*?\)', '', text)
    text = text.replace('--', '—')               # -- → — (표기 통일)
    text = re.sub(r'!{2,}', '!', text)           # !!! → !
    text = re.sub(r'\s{2,}', ' ', text)          # 다중 공백 정리
    return text.strip()


@dataclass
class TtsInput:
    cleaned_text: str
    instructions: str
    intensity: int
    speech_mode: str = "neutral"  # restrained | neutral | pressing | hesitant | cutting


# speech_mode → (stability_delta, style_delta) — intensity 기준값에 더하는 보조 축
_SPEECH_MODE_OFFSETS: dict[str, tuple[float, float]] = {
    "restrained": (+0.12, -0.10),  # 절제, 억누름 — 안정적이고 조용한 전달
    "neutral":    ( 0.00,  0.00),  # 기본값
    "pressing":   (-0.10, +0.12),  # 압박, 몰아붙임 — 불안정하고 강한 표현
    "hesitant":   (+0.08, -0.05),  # 망설임, 머뭇거림 — 다소 안정적이나 평평한 느낌
    "cutting":    (-0.08, +0.06),  # 끊음, 단호함 — 날카롭고 표현적
}


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


def build_tts_input(
    text: str,
    instructions: str,
    intensity: int = 2,
) -> TtsInput:
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


def _elevenlabs_voice_hints(instructions: str) -> tuple[float, float]:
    """instructions에서 delivery signal을 추출해 (stability_delta, style_delta) 반환.

    intensity 기준값에 더할 미세 조정치. 각 신호는 독립적으로 누적.

    ending_shape 신호:
      삼킴/눌림 → 절제된 끝맺음 (stability +0.08)
      올라감/열림/흘러나감 → 개방적 끝맺음 (stability -0.05)

    listener_pressure:
      압박: 강함 → 긴장감 (stability -0.08, style +0.10)

    delivery_mode:
      속삭/낮게 포함 → 조용한 전달 (stability +0.15, style -0.08)
      거칠/급/몰아 포함 → 거친 전달 (stability -0.05, style +0.06)
    """
    if not instructions:
        return 0.0, 0.0

    t = instructions.lower()
    s, st = 0.0, 0.0

    # ending_shape
    if '삼킴' in t or '눌림' in t:
        s += 0.08
    elif '올라감' in t or '열림' in t or '흘러나감' in t:
        s -= 0.05

    # listener_pressure
    if '압박: 강함' in t:
        s -= 0.08
        st += 0.10

    # delivery_mode
    if '속삭' in t or '낮게' in t:
        s += 0.15
        st -= 0.08
    elif '거칠' in t or '급' in t or '몰아' in t:
        s -= 0.05
        st += 0.06

    return s, st


def _generate_elevenlabs(
    voice_id: str,
    text: str,
    instructions: str,
    audio_path: Path,
    intensity: int,
    speech_mode: str = "neutral",
) -> None:
    """ElevenLabs TTS 호출.

    3단 voice_settings 결정:
      1) intensity(1~5) 기준값
      2) speech_mode 보조 축 offset (_SPEECH_MODE_OFFSETS)
      3) instruction signal 미세 조정 (_elevenlabs_voice_hints)
    """
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY가 설정되지 않았습니다.")

    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings

    # 1) intensity 기준값
    if intensity <= 2:
        stability, style = 0.70, 0.08
    elif intensity == 3:
        stability, style = 0.55, 0.20
    else:
        stability, style = 0.38, 0.40

    # 2) speech_mode 보조 축
    s_mode, st_mode = _SPEECH_MODE_OFFSETS.get(speech_mode, (0.0, 0.0))
    stability += s_mode
    style     += st_mode

    # 3) instruction signal 미세 조정 + clamp
    s_delta, st_delta = _elevenlabs_voice_hints(instructions)
    stability = max(0.10, min(1.00, stability + s_delta))
    style     = max(0.00, min(1.00, style     + st_delta))

    _log_tts_input("elevenlabs", voice_id, text, instructions, intensity, speech_mode, round(stability, 2), round(style, 2))

    el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    audio_iter = el_client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=ELEVENLABS_MODEL_ID,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=0.80,
            style=style,
            use_speaker_boost=False,
        ),
    )
    audio_path.write_bytes(b"".join(audio_iter))


def delete_session_files(session_id: str) -> None:
    """세션 디렉토리와 하위 파일 전체 삭제."""
    session_dir = AUDIO_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)


def check_elevenlabs_auth() -> dict:
    """ElevenLabs API key 설정 여부와 인증 성공 여부를 반환.

    실제 키 값은 절대 노출하지 않는다.
    반환: {"configured": bool, "auth_ok": bool, "detail": str}
    """
    if not ELEVENLABS_API_KEY:
        return {
            "configured": False,
            "auth_ok": False,
            "detail": "ELEVENLABS_API_KEY is missing.",
        }

    try:
        from elevenlabs.client import ElevenLabs
        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        el_client.user.get()
        return {
            "configured": True,
            "auth_ok": True,
            "detail": "ElevenLabs API authentication succeeded.",
        }
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg:
            detail = "Authentication failed with ElevenLabs API."
        elif "connection" in msg or "timeout" in msg or "network" in msg:
            detail = "Connection error reaching ElevenLabs API."
        else:
            detail = f"ElevenLabs API check failed: {type(e).__name__}"
        return {
            "configured": True,
            "auth_ok": False,
            "detail": detail,
        }
