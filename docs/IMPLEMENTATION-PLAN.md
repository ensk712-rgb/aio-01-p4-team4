# 티켓모아 구현 순서와 역할 분담 (팀 공유용)

2026-10-29 · 팀원 5명 · 마감 11/09(월) 14:50
함께 볼 것: 기획서 수정본(.docx), `TODO.md`(교시별 일정), `cases/README.md`(시나리오)

## 한눈에 보기

1. **계약부터 고정**: 본체 웹훅의 요청·응답 모양과 하위 웹훅끼리 주고받는 모양을 먼저 정한다.
2. **가짜로 끝까지 이어 놓기**: 모든 하위 워크플로우를 "고정된 가짜 답만 돌려주는" 빈 껍데기로 먼저 만들어 본체에 연결한다. 이 시점에 400·차단 시나리오가 통과한다.
3. **껍데기를 하나씩 진짜로 바꾸기**: 각자 자기 파일만 채운다. 채울 때마다 공통 시나리오를 다시 돌린다.
4. **예외·보안 붙이기**: 재시도, DLQ, 중복, 권한, 마스킹.
5. **동결 후 시험과 문서**: 82일차 11시 이후에는 워크플로우를 고치지 않는다.

이렇게 하면 다섯 명이 서로 기다리지 않고 동시에 일할 수 있다. 다른 사람 파일이 아직 껍데기여도 내 파일은 시험할 수 있기 때문이다.

## 역할 분담

| 역할 | 맡는 파일 | 맡는 데이터·문서 | 책임지는 시나리오 |
| --- | --- | --- | --- |
| **A 리드·통합**<br>최두나 | `ticketmoa-support` (본체: Webhook, 입력 검사, 주입 차단, 라우팅, 응답) | 레지스트리 JSON, 주제 제안서, 헌장, README, 데일리, 발표 | WF-08, WF-13, 전체 통합 |
| **B 오케스트레이션**<br>최강현 | `ticketmoa-agents` (Supervisor 분류, 보완 질문, 검증 Agent), `ticketmoa-refund` | 분류 프롬프트, 워크플로우 설계서 2~4절 | WF-02, 02b, TM-02, 03, 06, 13 |
| **C RAG**<br>정예진 | `ticketmoa-index`, `ticketmoa-search`, `ticketmoa-tech` | `knowledge/` 8개, RAG 설계서 전체 | WF-01, 03, 05, 12, TM-01, 07, 08 |
| **D 연동·안정성**<br>심환석 | `ticketmoa-payment`, `ticketmoa-handoff`, `ticketmoa-errors` | `data/users.json`, `records.json`, 워크플로우 설계서 5~7절 | WF-04, 06, 07, 09, 10, 11, TM-05, (가산) TM-09~12 |
| **E 시험·품질**<br>김인혜 | (워크플로우 없음) | `cases/`, `requests/`, `runs/`, 실행 결과서 | 모든 시나리오 실행·기록, 81일차부터 D의 Error Workflow 같이 보기 |

**규칙**
- 파일 하나는 한 사람만 고친다. 다른 사람 파일에 고칠 게 있으면 말로 부탁한다.
- 하위 워크플로우는 Execute Workflow가 아니라 **웹훅 경로**로 부른다 (팀원마다 n8n 워크플로우 ID가 달라서).
- 공통 계약(아래 1단계)은 A의 허락 없이 바꾸지 않는다.
- 커밋 메시지에 통과 수를 적는다. 예: `검증 Agent 추가 · common 9/14`

## 1단계 · 계약 고정 (80일차 오전, A 주도, 모두 참여)

**본체 계약 (과제 공통, 바꾸지 않음)**

```
POST /webhook/ticketmoa-support   (Header: X-Team-Key)
요청 {"request_id", "user", "channel", "question", "attempt", "context"}
응답 {"request_id", "route", "answer", "sources":[{doc,section,score}], "ticket",
      "agents", "security":{blocked_by,reason,masked}, "timings", "reason"}
route: 자동 답변 | 보완 질문 | 담당자 이관 | 권한 없음 | 차단
잘못된 입력: 400 {"error":"invalid request","codes":[...]}
```

**하위 웹훅끼리 주고받는 모양 (팀 내부 계약, 이 자리에서 확정)**

| 웹훅 | 받는 것 | 돌려주는 것 | 만드는 사람 |
| --- | --- | --- | --- |
| `ticketmoa-agents` | `{request_id, user, question, attempt, context, registry}` | `{intents, entities, sentiment, urgency, confidence, missing}` | B |
| `ticketmoa-search` | `{query, access_level, top_k}` | `{hits:[{doc, section, score, text}]}` | C |
| `ticketmoa-tech` (기술 장애·앱·일반 정보) | `{request_id, user, question, urgency, hits}` | `{route, answer, sources, alert}` | C |
| `ticketmoa-refund` | `{request_id, user, booking_id, context}` | `{route, answer, sources, pending_action}` | B |
| `ticketmoa-payment` (결제 오류·예매 조회) | `{request_id, user, record_id}` | `{status, record (가림), forbidden}` | D |
| `ticketmoa-handoff` | `{request_id, user, summary, category, priority}` | `{ticket, duplicate, dlq, alert}` | D |

모든 하위 웹훅은 실패해도 **200 + `{"error": "..."}`** 로 돌려주고, 본체는 HTTP Request에 timeout(예: 5초)을 두고 실패하면 이관으로 간다.

**끝 표시**: 위 표를 다섯 명이 모두 확인 (바꾸면 이 표부터 고친다. 설계서 3절은 구현 뒤 이 표로 쓴다).

## 2단계 · 가짜로 끝까지 이어 놓기 (80일차 5교시)

| 누가 | 할 일 |
| --- | --- |
| A | 본체: Webhook(Header Auth) → 입력 검사(빈 질문·없는 사용자·501자 → 400) → 주입 규칙 차단 → 하위 웹훅 호출 → Respond. 모양만 맞는 응답 |
| B·C·D | 자기 하위 웹훅을 **고정 답만 돌려주는 껍데기**로 만들어 push (Webhook → Set → Respond, 5분이면 됨) |
| E | `cases/common.json`을 팀 저장소에 넣고 한 번 돌려 출발점 기록 |

**끝 표시**: WF-08, WF-13 통과, 나머지는 실패해도 500 없이 응답이 온다.

## 3단계 · 각자 진짜로 채우기 (80일차 6교시 ~ 81일차 4교시)

순서가 서로 얽혀 있어서, **같은 줄은 동시에** 한다.

| 순서 | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| ① | 레지스트리 JSON, 라우팅 Switch | Supervisor 분류 (JSON 출력, 못 읽으면 이관) | `ticketmoa-index` 색인 (`ticketmoa_kb_v1_all` / `_staff`), 청크 길이 재기 | 데이터 API가 `users`·`records`를 읽게 설정, 도구 노드 3개 + Credential | 시나리오 질문 다듬기 (기대 결과는 그대로) |
| ② | 응답 조립 (sources, agents, timings) | 보완 질문 루프 (attempt 3회째 이관) | `ticketmoa-search` (사용자 권한별 메모리 키만 검색) | `ticketmoa-handoff` (요약 티켓, key=request_id, 알림) | 기능 붙을 때마다 공통 시나리오 재실행, 데일리 숫자 |
| ③ | 병렬: 검색 + 예매 조회 두 갈래 | 검증 Agent (답이 근거 안에 있는지, 아니면 이관) | `ticketmoa-tech` (QR·앱 트러블슈팅·공연장 FAQ, 긴급 시 대체 입장 + 알림) | `ticketmoa-payment` (본인 건만, 남의 건 403 → 권한 없음) | 81일차 출발점 기록 |
| ④ | 복합 문의 합치기 (WF-12) | `ticketmoa-refund` (1차 금액 안내 → 2차 확인 시 티켓) | 검색 점수 기준 재서 정하기 | 출력·로그 마스킹 (`masked` 개수) | 팀 시나리오 실행 |

**끝 표시 (81일차 4교시)**: WF-01, 02, 02b, 03, 05, 06, 07, 11, 12 통과.

## 4단계 · 예외와 보안 (81일차 5~7교시)

| 누가 | 할 일 | 시나리오 |
| --- | --- | --- |
| D | timeout·재시도 (429·5xx·timeout만, 401·403은 재시도 금지) | WF-11 |
| D | 티켓 API 장애 → `ticket: null` + DLQ + 알림 | WF-04 |
| D | 같은 request_id → `/cache`로 막고 같은 티켓 돌려주기 | WF-09 |
| D·E | `ticketmoa-errors` Error Workflow 게시, LLM 멈춤 시 이관 또는 근거 원문 | WF-10 |
| A | 실행 기록 `POST /logs` (개인정보 없이) | — |
| A·D | 설계서 5~7절 페이로드 표 | — |

**끝 표시 (81일차 8교시 중간 점검)**: 공통 14개 전부 통과 목표. 7개 미만이면 82일차에 가산을 하지 않는다.

## 5단계 · 동결·시험·문서 (82일차)

| 시각 | A | B | C | D | E |
| --- | --- | --- | --- | --- | --- |
| ~11:00 | 마지막 버그 수정 승인 | 프롬프트 안정화 | 색인 재생성 확인 | 장애 시나리오 재확인 | 전체 시험 `--repeat 3`, `bench` |
| 11:00~14:50 | README, 최종 병합, `tscan`, **제출** | 설계서 2~4절 | RAG 설계서 (잰 값) | 설계서 5~7절 | 결과서 (실패 사례 2건+) |
| 14:00~ | 발표 진행 | 시연 보조 | 시연 보조 | 시연 보조 | 시연 (리드 노트북) |

## 남은 수업을 어디에 쓰나

| 일차 | 수업 | 쓰는 곳 | 담당 |
| --- | --- | --- | --- |
| 76 (10/30) | 에러 처리·예외 대응 | 4단계 재시도·DLQ·Error Workflow의 출발 예제 | D |
| 77 (11/02) | 실행 로그 분석 | `POST /logs` 기록 칸, 결과서 숫자 뽑기 | A·E |
| 78 (11/03) | 데이터 품질 검증 | 색인 전 문서 검사(`ticketmoa-index`), records 검사 | C·E |
| 79 (11/04) | Ops Assistant | 하위 웹훅 부르기 설정, 가산 `ticketmoa-ops` | A·D |

PROMPTS.md는 "그 일차 예제가 있으면 그것, 없으면 72·73일차 예제"로 적어 두었다. 수업에서 배운 예제가 생기면 에이전트가 알아서 그쪽을 고른다.

## 매일 하는 git 순서 (모두)

```bash
git pull                                   # 1. 시작 전에 항상
# 2. n8n에서 내 워크플로우만 고친다
uv run tools/flow.py pull ticketmoa-<내파일>     # 3. n8n → JSON (키가 안 들어갔는지 확인)
uv run tools/flow.py check workflows/ticketmoa-<내파일>.json
uv run tools/flow.py test cases/common.json --webhook ticketmoa-support
tscan staged                               # 4. 커밋 전 비밀 검사
git add workflows/ticketmoa-<내파일>.json && git commit -m "무엇 · common N/14" && git push
```

다른 사람 작업을 내 n8n에서 보려면 `git pull` 후 `uv run tools/flow.py push workflows/*.json`, 색인은 `ticketmoa-index`를 한 번 다시 돌린다.

> `flow.py`는 저장소의 `tools/flow.py`를 쓴다 (78일차 `flow.py` + `X-Team-Key`). 키는 `FLOW_WEBHOOK_KEY` 환경 변수로만.
