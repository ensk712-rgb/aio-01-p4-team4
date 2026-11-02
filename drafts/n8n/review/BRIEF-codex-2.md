# Codex 2차 과제: 격리된 독립 검증 환경 작성

Claude가 `drafts/n8n/workflows/*.json`(10개, 생성기 build.mjs)을 작성 중이다. Codex는 **독립 시험 환경과 판정기**를 만든다. Claude의 코드에 맞추지 말고 문서·시나리오 기준으로 판정한다. Claude 설계는 `drafts/n8n/review/claude-1-design.md`.

## 쓰는 범위
`drafts/n8n/verify/` 안에만 쓴다. git 금지. 기존 컨테이너 day65-*, day67-* 와 서버 aio-t4 는 건드리지 않는다. `cases/`, `lib/`, `Last3Mon/`을 수정하지 않는다. 실제 API 키를 찾거나 읽지 않는다 (가짜 키만).

## 만들 것
1. `compose.yml` (project `ticketmoa-verify`): `n8nio/n8n:2.42.6` 포트 5699→5678, `python:3.12-slim`으로 `../../../../aio-01d4-stu/Last3Mon/77/data-api/server.py`를 읽기 전용 실행(서비스 이름·별칭 `data-api`, 포트 8899→8800, TZ=KST-9), `mock-openai` 포트 8898. 전용 네트워크, 데이터는 볼륨으로 쓰고 지울 수 있게.
2. `prepare-data.sh`: `runtime-data/`에 77 data-api/data를 복사한 뒤 employees.json=data/users.json, tickets.json=data/records.json, docs/=knowledge/*.md 만 (77 문서 제거).
3. `mock_openai.py` (표준 라이브러리): `/v1/chat/completions`, `/v1/embeddings`, `/v1/models`, `POST /admin/state` `{"mode":"ok|down|bad_json|bad_shape|slow|verifier_reject","slow_seconds":n}`. down은 401. system 메시지의 표지 `[ROLE:triage]`, `[ROLE:writer]`, `[ROLE:verifier]`로 역할 구분. 호출 수를 `GET /admin/stats`로 제공.
   - triage: user 메시지 `<question>…</question>` 안 질문에 키워드 규칙을 적용해 JSON 문자열 출력. `{"intents":[],"entities":{},"sentiment":"neutral|angry","urgency":"normal|high","confidence":0.0~1.0,"clarity":"clear|vague"}`. 등록 업무는 config/registry.json의 intent_id. "어제부터 계속 안 돼요" 류는 vague, confidence 0.3. "제휴 카드 포인트"는 intents [] + clear + 0.9 (등록 업무 밖).
   - writer: user 메시지 `<context>…</context>` 근거에서 문장을 뽑아 `{"answer":"…","grounded":true}`. 근거가 비면 grounded false.
   - verifier: `{"grounded":true,"policy_ok":true,"issues":[]}`.
   - embeddings: 결정적 벡터. 개념 사전(QR/모바일티켓, 로그인/인증, 결제/이중결제, 환불/취소, 주차, 입장 시간, 매크로, 암표, 현장 발권/대체 입장, 스태프/수기/책임자 코드)의 등장 수를 차원으로 쓰고, 소량의 해시 잡음을 더해 정규화. 같은 개념이면 0.8 이상, 개념이 없으면 0.2 이하가 되게. 그래야 점수 기준(0.35) 시험이 된다.
4. `credentials.json.example`와 등록 스크립트: id `ticketmoaOpenAi01`(openAiApi, url=http://mock-openai:8898/v1, 가짜 키), `ticketmoaDataApi1`(httpHeaderAuth, X-Api-Key, 가짜 값), `ticketmoaTeamKey1`(httpHeaderAuth, X-Team-Key, 시험 값). 이름은 `OpenAI`, `ticketmoa-data-api`, `ticketmoa-team-key`.
5. `up.sh`: 준비 → 기동 → import:workflow(drafts/n8n/workflows/*.json) → publish:workflow(하위부터, support 마지막, errors 먼저) → restart → 준비 대기 → `ticketmoa-index` 호출. `down.sh`: 이 프로젝트만 제거.
6. `runner.py`: Last3Mon/77/tools/flow.py의 `judge`, `field`, `as_text`와 같은 판정(복사)으로 cases/common.json, cases/team.json 실행. X-Team-Key 헤더 추가, before/after의 URL localhost:8800→localhost:8899, `{"llm":...}`→mock 상태, `--repeat n`, 파일 수정 없음. 결과 `verify/reports/*.json` 저장.
   - TM-09는 케이스 파일을 고치지 않고 러너에서 같은 질문을 5번 먼저 보낸다(요청 ID는 다르게).
   - 현재 날짜 2026-11-02는 C-2005의 예매일(11/04)보다 앞이다. 이 상태로 실행한다.
7. 판정기가 놓치는 것의 **엄격 검사**(코드 판정, 문서 근거 주석): ticket.id 존재, /tickets-created 건수, WF-04 DLQ 1·알림 1, WF-09 티켓 1건·같은 id, WF-12 답에 "현장 발권"과 "접수" 둘 다·알림 1·priority high, WF-08 mock 호출 0, 응답·/logs·/alerts·/dlq·/tickets-created 어디에도 연락처 원문 없음, 응답 9칸 전부 존재, 모든 응답 형식, TM-02 금액(C-2005: 152,000원, 수수료 0원) 표시.
8. **반례 스위트 `adversarial.json` + 러너 지원** (문서 근거로 기대 결과를 먼저 적는다):
   - 선행 안내 없이 confirm=true → 티켓 없음
   - 남의 booking_id로 confirm=true → 티켓 없음, 금액·상태 노출 없음
   - confirm=false → 티켓 없음
   - 확인 2회(다른 request_id) → 티켓 1건
   - 같은 request_id를 다른 사용자/다른 질문으로 → 원 응답 노출 없음
   - attempt 3의 명확한 질문 → 이관이 아니라 정상 처리
   - mock bad_json, bad_shape, down, verifier_reject → 200, 이관, 보완 질문 아님
   - tickets fault flaky → 재시도로 티켓 생성, error → DLQ, slow → 6초 안에 응답
   - C-2004(금액 없음)로 환불 요청 → 금액 계산 없이 안전 응답
   - 스태프 최현우의 WF-05 질문 → staff-entry-manual 사용 가능(대조군)
   - X-Team-Key 없음 → 본체와 하위 웹훅 모두 거부
   - 색인 전 검색 → indexed false 구분 (index 전에 측정)
   - 복합 "QR 안 떠요 + 남의 C-2001" → 남의 상태 노출 없음
   - 주입 문구가 context 값에 있어도 LLM 프롬프트에 들어가지 않음 (mock이 받은 메시지 기록으로 확인)

## 끝 표시
파일이 준비되면 `drafts/n8n/review/codex-2-harness.md`에 사용법과 한계를 쓰고 마지막 줄에 `CODEX-2-DONE`을 적고 멈춘다. n8n 워크플로우 파일이 아직 없으면 up.sh는 실행하지 않아도 된다. 다만 `mock_openai.py`와 `runner.py`의 단위 동작은 직접 확인한다.
