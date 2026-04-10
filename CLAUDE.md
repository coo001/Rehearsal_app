# Actor Rehearsal Service

## Mission
이 프로젝트는 배우가 AI 상대역과 자연스럽게 리허설할 수 있도록 돕는 풀스택 서비스다.

핵심 목표:
- 실제 상대 배우와 연습하는 느낌
- 클릭을 최소화한 자연스러운 진행
- 과장된 TTS 데모가 아니라 리허설 친화적 UX
- 빠른 실험이 가능하지만 코드베이스는 계속 확장 가능해야 함
- 프론트/백엔드/프롬프트/TTS가 하나의 제품 흐름으로 일관되게 동작해야 함

---

## Product Priorities
우선순위:
1. 전체 대본을 끝까지 연습 가능해야 한다
2. TTS 실패가 rehearsal 범위를 줄이면 안 된다
3. source-of-truth는 항상 전체 대본이다
4. 자연스러움이 화려함보다 중요하다
5. 작은 diff와 reviewability를 유지한다

---

## Engineering Principles

### 1. Natural over dramatic
- "더 극적"보다 "더 자연스러움"을 우선한다.
- 명시적으로 강한 장면이 아닌 이상 절제된 감정 표현을 선호한다.
- narrator-like delivery보다 actor-like delivery를 선호한다.

### 2. Minimal patch first
- 큰 리팩토링보다 최소 patch를 우선한다.
- 관련 없는 코드까지 수정하지 않는다.
- 먼저 작동하는 가장 단순한 버전을 만들고 이후 개선한다.

### 3. One responsibility per module
- 한 파일/함수에 너무 많은 책임을 몰아넣지 않는다.
- prompts / schemas / services / utils / api / frontend state 역할을 분리한다.
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

## Full-stack Rules

### Frontend
- 프론트는 사용자가 "지금 무엇을 해야 하는지" 한눈에 이해 가능해야 한다.
- stepper 표시와 실제 phase/state 흐름은 반드시 일치해야 한다.
- canonical script와 scoped subset은 명확히 분리한다.
- session restore, role selection, rehearsal state는 서로 오염되지 않게 관리한다.
- single-file frontend를 유지하더라도 state / reset rules / phase mapping / render responsibilities를 분리한다.

### Backend
- API는 프론트의 상태 흐름과 맞물려 예측 가능한 응답을 반환해야 한다.
- 에러 메시지는 원인을 분리해서 반환한다.
- partial success가 가능하면 hard fail보다 usable result를 우선한다.
- route / service / schema / util 책임을 섞지 않는다.

### Prompt / Parsing
- 프롬프트는 문학 비평용이 아니라 제품 기능용이어야 한다.
- 구조화된 출력(JSON)을 선호한다.
- 자유서술보다 제약된 필드를 선호한다.
- parser는 extraction 문제인지, JSON generation 문제인지, merge 문제인지 구분해서 다룬다.
- parse cache는 prompt/version/source hash 기준으로 안전하게 무효화되어야 한다.

### Audio / TTS
- TTS는 감정 과장보다 발화 목적, 서브텍스트, 템포, pause, ending shape를 반영해야 한다.
- 파일명은 예측 가능하고 디버깅 가능해야 한다.
- session / line index / character / short suffix를 포함하는 명명 규칙을 선호한다.
- TTS instruction은 짧고 실용적이어야 한다.
- provider별 formatting 전략(OpenAI vs ElevenLabs)을 분리할 수 있어야 한다.
- `(사이)`, hesitation, 말줄임표 등은 무조건 삭제하지 말고 pause signal로 검토한다.

### Session / Restore
- 복원된 이전 선택값은 default일 뿐 lock이 아니다.
- 이전 세션을 불러와도 사용자는 역할을 다시 선택할 수 있어야 한다.
- role change는 script-level state를 지우면 안 되고, run-level state만 무효화해야 한다.
- 기존 생성 음성은 가능한 한 재사용하고, 재생성은 꼭 필요할 때만 한다.

---

## Product Rules

### Rehearsal UX rules
- AI 대사는 자동으로 자연스럽게 이어져야 한다.
- 사용자 턴에서는 listening 상태가 명확해야 한다.
- 사용자가 말 끝나면 자동으로 다음 턴으로 넘어가는 흐름을 지향한다.
- fallback으로 수동 조작 수단도 유지한다.

### Source-of-truth rules
- rehearsal의 canonical source-of-truth는 전체 parsed script다.
- subset range는 runtime scope일 뿐 canonical data를 대체하면 안 된다.
- partial generation / partial analysis / restore state가 canonical scope를 축소하면 안 된다.

### Prompt rules
- practical direction > beautiful wording
- structured JSON > long prose
- beat_goal, subtext, delivery cue는 TTS와 rehearsal에 실제로 연결되어야 한다.

---

## Code Style Rules
- 함수는 가능한 한 하나의 책임만 가진다.
- endpoint 이름은 특별한 이유가 없으면 유지한다.
- pure helper function으로 분리 가능한 로직은 분리한다.
- config 값은 중앙화한다.
- 파일명, 경로 생성은 하드코딩하지 말고 helper를 사용한다.
- comments는 필요한 경우만 작성한다.
- 프론트 상태 변경은 명명된 helper/reset rule을 통해 수행한다.

---

## Required Workflow
작업 순서:
1. 문제를 먼저 구조화한다
2. 가장 가능성 높은 원인 2~4개를 제시한다
3. 최소 변경 계획을 제시한다
4. 승인 후 수정한다
5. 테스트/로그/edge case를 확인한다
6. 변경이 있으면 commit/push 조건을 검토한다

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
- main/master 직접 push는 기본 금지
- destructive command는 명시적 승인 없이 실행 금지

---

## Git Workflow
- 기본 작업 브랜치에서 수정한다.
- 코드 변경이 발생하면 가능한 경우 테스트/빌드/린트를 먼저 통과시킨다.
- commit 메시지는 변경 목적이 드러나게 짧고 명확하게 작성한다.
- auto push는 main/master가 아닌 브랜치에서만 허용한다.
- remote/origin이 없거나 인증 실패 시 push를 강제하지 않는다.

권장 commit 형식:
- feat: ...
- fix: ...
- refactor: ...
- chore: ...

---

## Validation Checklist
코드 수정 전후에 항상 확인:
- stepper와 실제 phase 이동이 일치하는가
- canonical script와 scoped subset이 분리되어 있는가
- restore 이후에도 역할 재선택이 가능한가
- TTS 실패가 rehearsal 범위를 줄이지 않는가
- parser partial failure가 전체 실패처럼 처리되지 않는가
- 로그만 봐도 실패 지점을 추적할 수 있는가

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
- full-stack consistency between frontend, backend, prompts, and TTS

When choosing between:
- more dramatic vs more natural -> choose more natural
- more abstract vs more explicit -> choose more explicit
- more ambitious refactor vs smaller safe patch -> choose smaller safe patch
- regenerate everything vs reuse safe existing assets -> choose reuse