# 역할별 첫 프롬프트 (바이브 코딩용) · 팀 티켓모아

각자 팀 저장소 폴더에서 코딩 에이전트를 켜고 자기 역할 프롬프트를 붙여 넣는다. 에이전트는 `AGENTS.md`를 먼저 읽는다.

**쓰는 법**
- 한 번에 한 단계만 시킨다. 단계가 끝날 때마다 n8n에 push하고 해당 시나리오를 돌려 본 뒤 다음 단계로 간다.
- `<...>` 칸은 직접 채운다.
- reference 파일 이름은 2026-11-03에 실습 폴더(68·69·71·72·73·76·77·78)에서 확인한 것이다. 79일차 폴더는 아직 없어서 79 예제를 쓰는 곳에는 대신 쓸 파일을 함께 적었다.
- 시험은 저장소의 `tools/flow.py`로 저장소 뿌리에서 돌린다. 78일차 `flow.py`를 그대로 부르면서 팀 웹훅에 `X-Team-Key`를 붙여 준다 (78 원본은 이 머리글을 보내지 않아 Header Auth를 걸면 401). 키는 셸에서만: `FLOW_WEBHOOK_KEY=<팀 키> uv run tools/flow.py test cases/common.json --webhook ticketmoa-support`
- 에이전트가 할 수 없는 일(손으로): n8n Credential 만들기, 워크플로우 활성화(Publish), 색인 웹훅 한 번 실행.

---

## 공통 · 0단계 · 연습 환경 (모두 같은 방법으로)

**78일차 실습 키트(`Last3Mon/78`)의 데이터 API와 `flow.py`를 쓴다.** 78일차 데이터 API에는 `/tickets`, `/alerts`, `/dlq`, `/logs`, `/cache`, 장애 스위치(`/admin/fault`)가 모두 있다. 데이터 API는 `data/employees.json`(이름·부서)과 `data/tickets.json`(접수 건)을 읽는데, 우리 `users.json`·`records.json`이 같은 칸 모양이라 파일만 바꿔 넣으면 된다.

```
AGENTS.md를 읽고 요약해 줘. 그다음 연습 환경을 만들어 줘.
1. ~/aio-01d4-stu/Last3Mon/78/data-api 폴더를 ~/ticketmoa-data-api 로 복사한다 (원본은 건드리지 않는다).
2. 복사본의 data/employees.json을 우리 data/users.json으로, data/tickets.json을 우리 data/records.json으로 바꾼다.
3. 복사본 데이터 API를 78일차와 같은 방법으로 켜고(README 참고), 아래를 확인해서 결과만 표로 알려 줘.
   - GET /employees/김하늘 → 200
   - GET /tickets/C-2002?requester=김하늘 → 200, requester=박서준 → 403
   - POST /tickets, POST /alerts, GET /dlq, /admin/fault 가 있는지 (없는 경로는 "없음"으로)
4. 시험은 저장소 뿌리에서 tools/flow.py(78 flow.py를 부르는 얇은 포장)로 돌린다: uv run tools/flow.py doctor 가 ready인지 먼저 본다.
5. 78 데이터 API는 X-Api-Key를 검사하지 않는다. Credential ticketmoa-data-api는 만들어 두되 값이 틀려도 지금은 통과한다는 것만 알아 둔다.
```

- 원래 실습 데이터 API를 켜 둔 채로 복사본을 켜면 포트(8800)가 겹친다. 하나만 켠다.
- 채점 기준 시나리오는 우리 `cases/common.json`이다. 기대 결과(expect)는 고치지 않는다.

---

## A · 리드·통합 · 최두나 (`ticketmoa-support`)

**1단계 · 골격 (80일차 5교시)**
```
AGENTS.md를 따른다. 나는 A 리드(최두나)이고 workflows/ticketmoa-support.json만 고친다.
~/aio-01d4-stu/Last3Mon/73/reference/lab01-example2-input.json을 workflows/ticketmoa-support.json으로 복사해서 출발해 줘.
- Webhook 경로 ticketmoa-support, Header Auth credential 이름 ticketmoa-team-key
- 입력 검사(Code): 빈 질문, data/users.json에 없는 user, 501자 이상이면 400 {"error":"invalid request","codes":[...]}
- 주입 차단(규칙, LLM 전에): "이전 지시 무시", "시스템 프롬프트" 같은 패턴이면 route "차단", security.blocked_by "rule"
- 그 외에는 아직 가짜 응답: route "자동 답변", answer "준비 중", sources []
- 응답은 AGENTS.md 3절의 칸을 모두 채운다
끝나면 flow.py check로 확인하고, WF-08과 WF-13만 돌려서 결과를 알려 줘.
```

**2단계 · 라우팅 (81일차)**
```
ticketmoa-support에서 가짜 분류를 지우고, HTTP Request로 /webhook/ticketmoa-agents를 불러 분류 결과를 받게 해 줘 (timeout 5초, 실패하면 담당자 이관).
분류 결과에 따라 Switch로 나눠 줘: confidence < 0.7 또는 missing이 있으면 보완 질문, intents에 따라 ticketmoa-tech(기술 장애·앱·일반 정보·부정 예매 문의 fair_booking) / ticketmoa-refund(환불) / ticketmoa-payment(결제 오류·예매 조회), 이관 조건이면(암표 신고 scalping_report 포함) ticketmoa-handoff.
기술 문의와 예매 조회가 함께 있으면 ticketmoa-search와 ticketmoa-payment를 두 갈래로 부르고 Merge로 합쳐 줘 (병렬).
하위 웹훅 호출의 HTTP Request 설정(timeout, 오류 출력)은 ~/aio-01d4-stu/Last3Mon/72/reference/lab03-example1-resilient.json을 따라 해 줘.
하위 웹훅이 주고받는 모양은 docs/IMPLEMENTATION-PLAN.md 1단계 하위 웹훅 표를 따른다. 공통 시나리오 전부 돌려서 통과 수를 알려 줘.
```

**3단계 · 실행 기록 (81일차 7교시)**
```
~/aio-01d4-stu/Last3Mon/77/reference/lab01-example2-report.json이 읽는 /logs 기록 칸을 따라, ticketmoa-support의 응답 직전에 POST /logs를 넣어 줘.
남길 것: request_id, route, intents, 하위 웹훅별 걸린 시간(ms), llm_calls, ticket 여부, security.blocked_by. 질문 원문과 연락처는 남기지 않는다.
실패해도 응답은 그대로 나가게(오류 출력 연결) 해 줘.
```

---

## B · 오케스트레이션 · 최강현 (`ticketmoa-agents`, `ticketmoa-refund`)

**1단계 · 껍데기 (80일차 5교시)**
```
AGENTS.md를 따른다. 나는 B(최강현)이고 workflows/ticketmoa-agents.json, workflows/ticketmoa-refund.json만 고친다.
두 웹훅을 고정 답만 돌려주는 껍데기로 만들어 줘 (Webhook → Set → Respond).
ticketmoa-agents는 {"intents":["tech_issue"],"entities":{},"sentiment":"neutral","urgency":"normal","confidence":0.9,"missing":[]}를 돌려준다.
```

**2단계 · Supervisor와 보완 질문 (81일차 2교시)**
```
~/aio-01d4-stu/Last3Mon/68/reference/lab02-example2-router.json을 참고해서 ticketmoa-agents에 분류 Agent를 넣어 줘.
- 모델 gpt-4.1-mini, Structured Output Parser로 {intents[], entities{booking_id, record_id}, sentiment, urgency, confidence, missing[]} 
- 업무 목록·설명·예시는 요청 본문의 registry에서 받아 프롬프트에 넣는다
- JSON을 못 읽으면 {"intents":[],"confidence":0} (본체가 이관)
- attempt가 3 이상이면 LLM을 부르지 않고 바로 이관 표시
WF-01, WF-02, WF-02b를 돌려 결과를 알려 줘.
```

**3단계 · 검증 Agent (81일차 3교시)**
```
~/aio-01d4-stu/Last3Mon/69/reference/lab02-start-reviewer.json(검토 Agent)과 lab03-example2-failsafe.json(못 읽으면 막기)을 참고해서, ticketmoa-agents에 /verify 역할을 추가해 줘.
입력 {answer, hits}, 출력 {"ok": true|false, "issues": []}. 답에 근거(hits) 밖 내용이 있으면 ok false. 못 읽으면 ok false.
```

**4단계 · 환불 2단계 (81일차 7교시)**
```
ticketmoa-refund를 만들어 줘. knowledge/refund-policy.md의 수수료 표를 Code 노드 규칙으로 옮긴다.
- context.confirm이 없으면: 예매 조회 → 환불 예정 금액 계산 → route "자동 답변", "확정하시겠어요?" 안내, ticket null
- 금액은 lib/common.js의 calcRefund로 계산한다. needsApproval(30만원 초과)이거나 관람 당일이면: 바로 route "담당자 이관" (티켓 category "refund", sources에 refund-policy)
- 1차 대기 상태는 /cache에 `pending:<user>:<booking_id>`로 저장한다. booking_id는 조회한 예매 기록의 값을 그대로 쓴다 (공연일로 만들지 않는다)
- context.confirm이 true면: /webhook/ticketmoa-handoff로 category "refund" 티켓 생성 → route "담당자 이관"
- 취소를 직접 실행하는 노드는 만들지 않는다
cases/team.json의 TM-02, TM-03, TM-06, TM-13을 돌려 줘.
```

---

## C · RAG · 정예진 (`ticketmoa-index`, `ticketmoa-search`, `ticketmoa-tech`)

**1단계 · 색인 (80일차 6교시)**
```
AGENTS.md를 따른다. 나는 C(정예진)이고 workflows/ticketmoa-index.json, ticketmoa-search.json, ticketmoa-tech.json과 knowledge/만 고친다.
~/aio-01d4-stu/Last3Mon/71/reference/lab01-example2-index.json을 workflows/ticketmoa-index.json으로 복사해서 출발해 줘.
- knowledge/*.md를 ## 절 단위로 청킹, 메타데이터 {doc, section, access_level}
- access_level이 staff인 문서는 메모리 키 ticketmoa_kb_v1_staff, 나머지는 ticketmoa_kb_v1_all
- 임베딩 text-embedding-3-large
- 응답으로 문서 수, 청크 수, 청크 길이 최소·중앙값·최대를 돌려준다 (RAG 설계서에 쓸 값)
- 색인 전에 품질 검사(Code): 문서마다 `##` 절 3개 이상, access_level 줄이 있음, 빈 절 없음, 연락처 형식 문자열 없음. 걸리면 그 문서는 색인하지 않고 응답의 issues에 적는다. 규칙 모양은 ~/aio-01d4-stu/Last3Mon/78/reference/lab03-example1-schema-check.json을 따른다.
```

**2단계 · 검색 (81일차 2교시)**
```
~/aio-01d4-stu/Last3Mon/71/reference/lab01-example2-search.json을 복사해서 ticketmoa-search를 만들어 줘.
입력 {query, access_level, top_k}, 출력 {hits:[{doc, section, score, text}]}.
access_level이 all이면 ticketmoa_kb_v1_all만, staff면 둘 다 검색한다 (검색 전 필터).
WF-01, WF-03, WF-05 질문으로 점수를 뽑아서 표로 보여 줘. 자동 답변 점수 기준을 정하는 데 쓴다.
```

**3단계 · 기술 장애 (81일차 4교시)**
```
ticketmoa-tech를 만들어 줘. 기술 장애·앱·일반 정보(주차·입장 시간 등)·부정 예매 문의(매크로 제한·해외 예매, fair-booking-policy)를 모두 맡는다. ticketmoa-search 결과로 gpt-4.1-mini가 답을 쓰고 sources를 채운다.
urgency가 high(공연 30분 이내 입장 문제)면 knowledge/onsite-entry-fallback.md의 대체 입장 방법을 먼저 쓰고, alert {"channel":"venue-staff","priority":"high"}를 돌려준다.
hits가 없거나 점수가 기준 미만이면 route "담당자 이관", sources [].
WF-01, WF-12, TM-01을 돌려 주고, "다음 주 토요일 공연 주차 돼요?"(venue-faq)도 한 번 확인해 줘.
```

---

## D · 연동·안정성 · 심환석 (`ticketmoa-payment`, `ticketmoa-handoff`, `ticketmoa-errors`)

**1단계 · 도구 노드 (80일차 7교시)**
```
AGENTS.md를 따른다. 나는 D(심환석)이고 workflows/ticketmoa-payment.json, ticketmoa-handoff.json, ticketmoa-errors.json과 data/만 고친다.
~/aio-01d4-stu/Last3Mon/73/reference/lab02-example1-own.json을 workflows/ticketmoa-payment.json으로 복사해서 출발해 줘.
- GET /tickets/<record_id>?requester=<user>, credential ticketmoa-data-api
- 403이면 {"forbidden": true}, 본인 건이면 record를 돌려주되 contact는 가린다
WF-06, WF-07을 돌려 줘.
```

**2단계 · 이관 (81일차 3교시)**
```
~/aio-01d4-stu/Last3Mon/76/reference/lab02-example1-dlq.json을 출발점으로 ticketmoa-handoff를 만들어 줘 (재시도 모양은 72/reference/lab03-example1-resilient.json 참고).
- POST /tickets {key: request_id, title, requester, category, priority}, 같은 key면 duplicate true
- 재시도는 429·5xx·timeout만 2회, 401·403은 재시도 없이 중단 + 알림
- 끝까지 실패하면 POST /dlq 1건 + POST /alerts 1건, ticket null
- 요약 본문에 연락처 원문을 넣지 않는다
WF-03, WF-04, WF-09를 돌려 줘 (WF-04는 fault 켜고 끄는 before/after가 시나리오에 있다).
```

**3단계 · Error Workflow와 LLM 멈춤 (81일차 6~7교시)**
```
~/aio-01d4-stu/Last3Mon/76/reference/lab02-example2-error-handler.json(Error Workflow)과 72/reference/lab03-example2-llm-fallback.json(LLM 멈춤)을 참고해서
1) ticketmoa-errors: Error Trigger → POST /alerts (워크플로우 이름, 노드 이름, 시각만. 질문 원문·연락처 없이)
2) LLM이 멈췄을 때 본체가 500 대신 담당자 이관을 돌려주려면 어느 노드에 무엇을 두어야 하는지 A에게 전할 메모를 써 줘 (ticketmoa-support는 내가 고치지 않는다)
WF-10, WF-11을 돌려 줘.
```

**4단계 · 가산: 매크로·해외 IP 차단 (82일차, 필수 통과 뒤에만)**
```
lib/common.js의 checkRateLimit과 checkIpPolicy, config/ip-policy.json을 써서
ticketmoa-support의 입력 검증 바로 뒤, LLM 앞에 넣을 Code 노드 코드와 연결 위치를 A(최두나)에게 줄 메모로 써 줘.
- 사용자별 최근 요청 시각은 /cache에 저장, 6번째면 route 차단, security.blocked_by "rate_limit"
- context.client_ip가 있으면 checkIpPolicy, 막히면 route 차단, blocked_by "geo" 또는 "ip_blocklist", 답은 fair-booking-policy 3절 문구
- client_ip가 없으면 그냥 통과 (공통 시나리오에 영향 없음)
TM-09~12와 common.json 전체를 돌려 공통 결과가 그대로인지 확인해 줘.
```

---

## E · 시험·품질 · 김인혜

**1단계 · 출발점 (80일차 5교시 뒤)**
```
AGENTS.md를 따른다. 나는 E(김인혜)이고 cases/, requests/, runs/, docs/EXECUTION-RESULT.md만 고친다.
cases/common.json을 --webhook ticketmoa-support로 돌리고, 케이스별 통과/실패와 실패 이유를 표로 정리해 줘.
보고서 JSON은 runs/에 날짜를 붙여 복사해 줘. 기대 결과(expect)는 절대 고치지 않는다.
```

**2단계 · 매일 회귀 (81일차)**
```
누군가 push했다고 하면: git pull → flow.py push workflows/*.json → ticketmoa-index 한 번 호출 → common.json과 team.json 실행 → 어제보다 줄어든 케이스가 있으면 어느 파일 변경 뒤인지 git log로 찾아서 알려 줘.
```

**3단계 · 최종 (82일차 2~3교시)**
```
공통과 팀 시나리오를 --repeat 3으로 돌리고, bench로 p50·p95를 재 줘.
~/aio-01d4-stu/Last3Mon/77/reference/lab01-example2-report.json의 로그 분석 방법으로 /logs에서 route 비율, 하위 웹훅별 p50·p95, 요청당 llm_calls를 뽑아 줘.
docs/EXECUTION-RESULT.md 템플릿의 결과 요약 칸을 runs/ 숫자로만 채워 줘. 실패 사례 2건 이상은 원인·조치·재시험 결과를 쓴다. 숫자를 추정해서 쓰지 않는다.
```

---

## 가산 · Ops Assistant (82일차 오전, 필수 시나리오가 다 통과한 뒤에만)

```
~/aio-01d4-stu/Last3Mon/79/reference/ 의 Ops Assistant 예제(79일차 수업 뒤 생김, 없으면 77/reference/helpdesk-live.json)를 workflows/ticketmoa-ops.json으로 복사해서,
우리 /logs와 /tickets-created, /dlq를 읽어 "오늘 이관 비율, 가장 느린 하위 웹훅, DLQ 건수"를 답하게 해 줘.
ticketmoa-support와 다른 파일은 고치지 않는다.
```
