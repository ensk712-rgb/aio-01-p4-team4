# 티켓모아 단위 프로젝트 TODO

마감 **2026-11-09(월) 14:50** (기본 브랜치 마지막 커밋) · 같은 날 17:00 평가 시험 25문항
역할: A 리드·통합(최두나) · B 오케스트레이션(최강현) · C RAG(정예진) · D 연동·안정성(심환석) · E 시험·품질(김인혜)

표시: [x] 끝남 · [~] 초안 있음 (사람이 읽고 고쳐야 함) · [ ] 아직

## 0. 지금까지 만든 초안 (`/mnt/project-files/ticketmoa/`)

- [~] 기획서 수정본 `통합 고객지원 멀티에이전트 기획서 (수정).docx`
- [~] 주제 제안서 `TOPIC.md` (팀 이름: 티켓모아)
- [~] 지식 문서 8개 `knowledge/` (관리자 전용 `staff-entry-manual` 포함)
- [~] `data/users.json` 5명, `data/records.json` 5건 (C-2001~C-2005)
- [~] `cases/common.json` 14유형 17케이스, `cases/team.json` 13개 (TM-09~12 가산)

## 1. 80일차 전 (지금 ~ 11/04)

- [x] **A** 팀원 5명 역할 확정, 가상 브랜드명 확정 (티켓모아)
- [ ] **A** 기획서 수정본을 팀이 함께 읽고 합의
- [ ] **C** 지식 문서 8개 읽고 고치기 (숫자가 문서끼리 맞는지: 30분, 수수료 표, 30만원)
- [ ] **D** users·records 칸 이름 확인, 시연에 필요한 기록 더 필요한지 판단
- [ ] **E** 시나리오 질문이 실제 고객 말투인지 다듬기, 기대 결과는 그대로
- [ ] **모두** 각자 WSL에서 n8n·데이터 API 켜지는지, OpenAI 키 Credential 확인
- [ ] **모두** git 기본 명령(clone·pull·add·commit·push) 한 번씩 연습

## 2. 80일차 (11/05 목) · 설계와 골격

| 교시 | 할 일 | 담당 | 끝 표시 |
| --- | --- | --- | --- |
| 1 | 78일차 데이터 API 복사본 켜기, `flow.py doctor` (`docs/PROMPTS.md` 0단계) | 모두 | 모두 `ready` |
| 2 | **주제 제안서 강사 승인 (10:30)**, 팀 헌장, 비공개 팀 저장소 만들기·초대, `AGENTS.md`, `flow.py doctor` | A | `docs/TOPIC.md`, `docs/TEAM-CHARTER.md`, 모두 `ready` |
| 3 | 초안을 저장소에 넣기 (`knowledge/`, `data/`, `cases/`), 데이터 API가 팀 데이터를 읽게 설정 | C·D | `GET /tickets/C-2002?requester=김하늘` 200, 남의 건 403 |
| 4 | 워크플로우 설계서 1~4절 초안 (업무 시나리오·전체 흐름·흐름도·역할 표·분기) | A·B | 설계서 1~4절 |
| 5 | **1차 점검 (팀별 10분)**: 범위, 설계서 1~4절, 공통 계약, `cases/common.json`, 본체 400·주입 차단 | A | WF-08, WF-13 통과 |
| 6 | 색인 `ticketmoa-index`: 청킹·임베딩·`ticketmoa_kb_v1_all`/`_staff` 저장, 청크 길이 분포 재기 | C | 색인 개수, RAG 설계서 1~2절 |
| 7 | 도구 노드: 예매 조회·`POST /tickets`(key=request_id)·`POST /alerts`, Credential(`X-Api-Key`), **팀 VM 첫 배포·색인** | D·A | 도구마다 `call` 한 번, VM에서 `push`·`tools/reindex.py` |
| 8 | **발표 ① (팀별 10분)**: 팀 VM에서 시연, 설계서 1~4절, RAG 설계서 1~2절, 공통 시나리오 통과 수, 데일리 | A·E | 피드백 칸, `docs/daily/DAY80.md` |

## 3. 81일차 (11/06 금) · 구현과 예외 처리

| 교시 | 할 일 | 담당 | 끝 표시 |
| --- | --- | --- | --- |
| 1 | 공통 시나리오 한 번 돌려 출발점 기록 | E | 통과 수 |
| 2 | Supervisor(레지스트리 → 분류 프롬프트) + `ticketmoa-search` + 답변 Agent | B·C | WF-01 |
| 3 | 검증 Agent, 신뢰도 분기, `ticketmoa-handoff`(요약 티켓·알림) | B·D | WF-03 |
| 4 | 보완 질문 루프(attempt 3회째 이관), 병렬(검색 + 예매 조회), 복합·긴급(대체 입장 + 현장 알림), **중간 점검** | B·A | WF-02, 02b, 11, 12 |
| 5 | 본인 건만, 문서 권한(검색 전 필터), 출력·로그 개인정보 가림 | D | WF-05, 06, 07 |
| 6 | timeout·재시도(429·5xx·timeout만), DLQ·알림, 중복 요청(`/cache`), LLM 멈춤 대비 | D | WF-04, 09, 10 |
| 7 | `ticketmoa-errors` Error Workflow 게시, 실행 기록 `/logs`, 설계서 5~7절 페이로드 표 | D·A | 설계서 5~7절 |
| 7 (병행) | 환불 2단계 확인 (`ticketmoa-refund`), 이중결제 이관 (`ticketmoa-payment`) | B·D | TM-02, 03, 05, 06 |
| 8 | **발표 ②·기능 동결**: 공통 시나리오 실행 화면 + 남은 것, 데일리 | A·E | `docs/daily/DAY81.md` |

> 중간 점검에서 공통 시나리오가 절반(7개) 미만이면 82일차에는 가산을 멈추고 필수만 한다.

## 4. 82일차 (11/09 월) · 시험·제출·발표

| 시각 | 할 일 | 담당 | 끝 표시 |
| --- | --- | --- | --- |
| 1교시 | 마지막 수정 범위 정하기 (기능 동결은 81일차 8교시, **11시 뒤로 워크플로우 수정 금지**) | A | |
| 2교시 | 공통·장애·팀 시나리오 전부, LLM 들어간 것 `--repeat 3`, `bench` | E | `runs/*.json` |
| 3교시 | 실패 원인·조치·재시험 (실패 사례 2건 이상), 결과서 숫자 | E | 결과서 1~4절 |
| 4교시 | 설계서 둘·결과서·README 마무리, `tscan scan .`, **14:50까지 제출** | 모두 | 마지막 커밋 |
| 7교시 (16:00) | 발표 20분 + 질의 5분, 데모 시나리오 4개 시연 (리드 노트북 한 대) | A + 모두 | |
| 17:00 | 평가 시험 | 모두 | |

## 5. 만들어야 할 워크플로우 (한 사람 = 한 파일)

| 파일 | 웹훅 | 담당 | 관련 시나리오 |
| --- | --- | --- | --- |
| `workflows/ticketmoa-support.json` (본체) | `/webhook/ticketmoa-support` | A | 전부, WF-08·13 |
| `workflows/ticketmoa-index.json` (색인) | `/webhook/ticketmoa-index` | C | — |
| `workflows/ticketmoa-search.json` (검색) | `/webhook/ticketmoa-search` | C | WF-01·03·05 |
| `workflows/ticketmoa-tech.json` (기술 장애·앱·일반 정보 RAG 답변) | `/webhook/ticketmoa-tech` | C | WF-01·12, TM-01 |
| `workflows/ticketmoa-refund.json` (환불 2단계) | `/webhook/ticketmoa-refund` | B | TM-02·03·06 |
| `workflows/ticketmoa-payment.json` (결제 오류·예매 조회) | `/webhook/ticketmoa-payment` | D | WF-06·07·11, TM-05 |
| `workflows/ticketmoa-handoff.json` (티켓·알림·DLQ) | `/webhook/ticketmoa-handoff` | D | WF-02b·03·04·09 |
| `workflows/ticketmoa-errors.json` (Error Workflow) | Error Trigger | D | WF-10 |

| `workflows/ticketmoa-agents.json` (Supervisor·보완 질문·검증) | `/webhook/ticketmoa-agents` | B | WF-02·02b, 검증 |

A와 B가 같은 파일을 고치지 않도록 Supervisor·검증 Agent는 본체에서 떼어 `ticketmoa-agents`로 둔다. 구현 순서와 하위 웹훅끼리 주고받는 모양은 `IMPLEMENTATION-PLAN.md`.

## 6. 제출물 체크리스트

- [ ] `README.md` (팀·역할·실행 방법·웹훅 경로·시연 순서)
- [ ] `AGENTS.md`
- [ ] `docs/TOPIC.md`, `docs/TEAM-CHARTER.md`
- [ ] `docs/WORKFLOW-DESIGN.md` (35점, 연결선마다 페이로드 표, 노드 이름 = 실제 노드 이름)
- [ ] `docs/RAG-ARCHITECTURE.md` (30점, 청킹 비교·임베딩 선정 이유·메타데이터·백업/복구·확장, **잰 값**)
- [ ] `docs/EXECUTION-RESULT.md` (25점, `runs/` 숫자만, 실패 사례 2건+, KSM-REQ 6절 체크리스트 15개)
- [ ] `docs/daily/` 3장, `docs/images/` (개인정보·키 가림)
- [ ] `workflows/*.json` (키 없음)
- [ ] `knowledge/`, `data/`, `cases/common.json`, `cases/team.json`, `requests/`, `runs/`
- [ ] `tscan scan .` 0건, 강사가 README대로 다시 돌려 같은 결과

## 7. 가산 (필수가 다 통과한 뒤에만)

- [ ] 웹 채팅 위젯 (예시 화면 ①②, Webhook 호출)
- [ ] 상담원 콘솔 (예시 화면 ③, 티켓 목록 표시)
- [ ] 실제 Slack 알림
- [ ] 레지스트리에 업무 하나 추가하는 라이브 데모 (예: 양도 문의)
- [ ] PGVector로 색인 보존
- [ ] Ops Assistant `ticketmoa-ops` (79일차 예제, 로그·티켓·DLQ 요약)

## 8. 열린 질문

- [ ] 본인 확인: `user`만으로 할지, 예매번호 뒷자리 확인을 더할지
- [ ] Supervisor 1단계 vs 대분류 → 세부 2단계
