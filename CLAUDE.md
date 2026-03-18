# Actor Rehearsal Service

## Product Goal
이 프로젝트는 배우가 AI 상대역과 자연스럽게 리허설할 수 있도록 돕는 서비스다.

핵심 목표:
- 실제 상대 배우와 연습하는 느낌
- 클릭을 최소화한 자연스러운 진행
- 과장된 TTS 데모가 아니라 리허설 친화적 UX
- 빠른 실험이 가능하지만 코드베이스는 계속 확장 가능해야 함

---

## Engineering Principles

### 1. Natural over dramatic
- "더 극적"보다 "더 자연스러움"을 우선한다.
- 명시적으로 강한 장면이 아닌 이상, 절제된 감정 표현을 선호한다.
- narrator-like delivery보다 actor-like delivery를 선호한다.

### 2. Minimal patch first
- 큰 리팩토링보다 최소 patch를 우선한다.
- 관련 없는 코드까지 수정하지 않는다.
- 먼저 작동하는 가장 단순한 버전을 만들고, 이후 개선한다.

### 3. One responsibility per module
- 한 파일/함수에 너무 많은 책임을 몰아넣지 않는다.
- prompts / schemas / services / utils / api 역할을 분리한다.
- 새 기능 추가 시 기존 파일에 무조건 누적하지 말고 책임 분리를 먼저 검토한다.

### 4. Plan before code
- 기능 구현 전 항상 최소 변경 계획을 먼저 제시한다.
- 변경 파일, 상태 흐름, 리스크, 테스트 항목을 먼저 정리한다.
- 계획 승인 후 코드 패치를 진행한다.

### 5. Reviewability matters
- 변경은 작은 diff로 유지한다.
- startup code review에서 바로 읽히는 수준의 단순함을 유지한다.
- 불필요한 추상화, 깊은 클래스 구조, 과한 패턴 도입을 피한다.

---

## Product Rules

### Rehearsal UX rules
- AI 대사는 자동으로 자연스럽게 이어져야 한다.
- 사용자 턴에서는 listening 상태가 명확해야 한다.
- 사용자가 말 끝나면 자동으로 다음 턴으로 넘어가는 흐름을 지향한다.
- fallback으로 수동 조작 수단도 유지한다.

### Prompt rules
- 프롬프트는 문학 비평용이 아니라 제품 기능용이어야 한다.
- 구조화된 출력(JSON)을 선호한다.
- 자유서술보다 제약된 필드를 선호한다.
- practical direction > beautiful wording

### Audio/TTS rules
- 파일명은 예측 가능하고 디버깅 가능해야 한다.
- session / line index / character / short suffix를 포함하는 명명 규칙을 선호한다.
- TTS instruction은 짧고 실용적이어야 한다.

---

## Code Style Rules
- 함수는 가능한 한 하나의 책임만 가진다.
- endpoint 이름은 특별한 이유가 없으면 유지한다.
- pure helper function으로 분리 가능한 로직은 분리한다.
- config 값은 중앙화한다.
- 파일명, 경로 생성은 하드코딩하지 말고 helper를 사용한다.
- comments는 필요한 경우만 작성한다.

---

## Output Rules for Claude Code
작업 시 반드시 다음 순서를 따른다:

1. 먼저 변경 계획을 짧게 설명
2. 변경 파일 목록 제시
3. 수정 코드만 제시
4. 관련 없는 리팩토링 금지
5. 왜 이렇게 바꿨는지 짧게 설명
6. 수동 테스트 3개 제시
7. edge case 3개 제시

---

## Constraints
- 전체 아키텍처 재설계 금지
- 불필요한 클래스/패턴 도입 금지
- 작은 코드베이스에 과도한 enterprise 구조 도입 금지
- async queue, Docker, k8s 등은 지금 단계에서 기본 도입 금지
- 코드가 길어지더라도 이해하기 쉬운 명시적 구조를 우선한다

---

## Default Prompting Preference
Claude Code should prefer:
- simple module split
- explicit naming
- stable JSON
- practical UX
- minimal patch
- easy future testing
- natural actor rehearsal flow

When choosing between:
- more dramatic vs more natural -> choose more natural
- more abstract vs more explicit -> choose more explicit
- more ambitious refactor vs smaller safe patch -> choose smaller safe patch