# 🎭 AI 대본 연습 시스템

OpenAI + ElevenLabs를 활용한 인터랙티브 대본 연습 환경

## 설치 및 실행

**Python 3.10 이상 필요** (3.10+ union type 문법 사용)

### 1. 패키지 설치
```bash
cd rehearsal_app
pip install -r requirements.txt
```

### 2. API 키 설정
프로젝트 루트에 `.env` 파일을 생성하고 아래 내용을 입력:
```
# 필수
OPENAI_API_KEY=sk-...

# TTS provider 선택: elevenlabs (기본) 또는 openai
TTS_PROVIDER=elevenlabs

# ElevenLabs 사용 시 필수
ELEVENLABS_API_KEY=sk_...
```

선택 설정 (기본값으로 동작):
```
# 모델 라우팅 (기본값 사용 권장)
OPENAI_PARSE_FAST_MODEL=gpt-5.4-mini
OPENAI_PARSE_PDF_MODEL=gpt-5.4
OPENAI_ENRICH_MODEL=gpt-5.4
OPENAI_VOICE_ASSIGN_MODEL=gpt-5.4-mini

# ElevenLabs 모델 ID
ELEVENLABS_MODEL_ID=eleven_multilingual_v2

# CORS (운영 배포 시 설정)
ALLOWED_ORIGINS=https://example.com
```

### 3. 실행
```bash
python app.py
```
브라우저에서 http://localhost:8000 접속

## 사용 방법

1. **대본 입력** - 대사와 지문이 포함된 대본 붙여넣기 또는 PDF 업로드
2. **목소리 배정** - 캐릭터들에게 AI 목소리 자동 배정 (OpenAI GPT 사용)
3. **연습 범위 선택** - 전체 대본 또는 특정 구간만 선택
4. **음성 생성** - 상대 대사 AI 음성 자동 생성 (ElevenLabs 또는 OpenAI TTS)
5. **역할 선택** - 내가 연습할 캐릭터 선택
6. **리허설 시작** - 상대 대사 자동 재생, 내 대사는 직접 읽기

## 대본 형식

```
캐릭터A
대사 내용입니다.

캐릭터B
(행동 묘사) 다른 대사입니다.

[무대 지문]
```

## 기술 스택
- **OpenAI API** - 대본 파싱 & 캐릭터 분석 & 목소리 배정 (GPT), OpenAI TTS 사용 시 음성 합성
- **ElevenLabs API** - AI 음성 합성 (기본 provider, `eleven_multilingual_v2` 모델)
- **FastAPI** - 백엔드 API
- **Vanilla JS** - 프론트엔드
