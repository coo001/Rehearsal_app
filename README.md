# 🎭 AI 대본 연습 시스템

Claude + ElevenLabs를 활용한 인터랙티브 대본 연습 환경

## 설치 및 실행

### 1. 패키지 설치
```bash
cd rehearsal_app
pip install -r requirements.txt
```

### 2. API 키 설정
`.env.example`을 복사해서 `.env` 파일 생성:
```bash
cp .env.example .env
```
`.env` 파일을 열어 API 키 입력:
```
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=sk_...
```

### 3. 실행
```bash
python app.py
```
브라우저에서 http://localhost:8000 접속

## 사용 방법

1. **대본 입력** - 대사와 지문이 포함된 대본 붙여넣기 (샘플 제공)
2. **캐릭터 분석** - Claude AI가 자동으로 등장인물과 성격 분석
3. **역할 선택** - 내가 연습할 캐릭터 선택
4. **목소리 배정** - 상대 캐릭터들에게 ElevenLabs 목소리 배정
5. **음성 생성** - 상대 대사 AI 음성 자동 생성
6. **연습 시작** - 상대 대사 자동 재생, 내 대사는 직접 읽기

## 대본 형식

```
캐릭터A
대사 내용입니다.

캐릭터B
(행동 묘사) 다른 대사입니다.

[무대 지문]
```

## 기술 스택
- **OPENAI_API** - 대본 파싱 & 캐릭터 분석, AI 음성 합성 (eleven_multilingual_v2)
- **FastAPI** - 백엔드 API
- **Vanilla JS** - 프론트엔드
