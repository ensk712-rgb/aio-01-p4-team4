# 기능별 검증 표

> 기준 원문: `Lecture/80-82-Project/Req/KSM-REQ.md` 6절 제출 전 체크리스트 (총 15개 항목: 노코드 워크플로우 설계서 4 · RAG 아키텍처 설계서 4 · 워크플로우 실행 결과서 4 · 공통 3)
> 현재 정책: 로그인·세션·개인 인증은 의도적으로 범위에서 제외한다. 공개 기술지원·FAQ·이관과 함께 본인 문의 조회(요청 `user`와 `requester` 일치, 사칭은 막지 못함)와 환불 2단계를 제공하고, 직원 전용 검색은 제공하지 않는다.
> 최신 전체 VM 회귀: 2026-11-07 18:33~18:43 KST T행: 공통 **51/51**, 팀 **13/13**, 보안 **8/8**, `bench -n 5` p50 5.61초·p95 6.59초(실패 0/5). 재시작·재색인·예열 뒤 측정이다. 같은 워크플로우의 예열 없는 S행은 공통 **50/51**(WF-01 첫 호출 8.0초)이고 첫 예열 호출도 8.8초여서 WF-01 간헐 지연은 미결이다. 차단 정책 시기 R행 **48/51**, 16:10 O행 **50/51**·팀 **11/13**, 과거 N행 **51/51**은 코드와 기대값이 다른 이력이다. 자세한 분리는 `docs/EXECUTION-RESULT.md` 0절을 따른다.

---

## 1. KSM-REQ 6절 15개 항목 검증 표 (설계서 4 · RAG 4 · 결과서 4 · 공통 3)

| # | 구분 | 검증 항목 (`KSM-REQ.md` 6절 원문) | 구현 워크플로우 · 산출물 위치 | 검증 시나리오 · 실측 근거 (`runs/` · `runs/vm/`) | 충족 |
| :---: | --- | --- | --- | --- | :---: |
| 1 | **노코드 워크플로우 설계서** (1/4) | Trigger → 처리 → 출력 흐름이 실제 구현과 일치한다. | `docs/WORKFLOW-DESIGN.md` 2~3절, `workflows/ticketmoa-*.json` **10개** (`support`, `agents`, `refund`, `index`, `search`, `tech`, `payment`, `handoff`, `errors`, 가산 `ops`) | 11/07 대조: 개인 조회 복구로 3.1절 그림의 `tech_lookup`·`refund`·`payment` 갈래가 현재 연결과 다시 일치한다 | [x] |
| 2 | **노코드 워크플로우 설계서** (2/4) | 병렬·분기·루프 구조의 사용 목적이 명확하다. | `docs/WORKFLOW-DESIGN.md` 4절 (`Plan route`·`Route` 분기, `Call search ∥`·`Call payment ∥` 병렬, `attempt` 보완 질문 루프 및 재시도 루프) | 분기·병렬·루프가 모두 현재 경로다(T행 WF-02·02b·12 통과) | [x] |
| 3 | **노코드 워크플로우 설계서** (3/4) | 외부 연동별 인증 및 오류 처리를 기록했다. | `docs/WORKFLOW-DESIGN.md` 5·7절 (`X-Team-Key`, `X-Api-Key`, `OpenAI (.env)` 인증 및 401/403 비재시도, 429/5xx/timeout 재시도·DLQ·알림·Error Workflow) | `WF-04`(티켓 API 500 → DLQ+알림, 3/3), `WF-10`(LLM 멈춤 → 이관, 3/3), 기록 완료. `WF-11` 8초 지연 이관(5.6초)은 차단 전 이력이고, R행 3/3은 느린 API를 지나지 않아 지연 처리 검증이 아니다 | [x] |
| 4 | **노코드 워크플로우 설계서** (4/4) | 노드 간 페이로드의 필수·선택 필드와 변환 로직을 작성했다. | `docs/WORKFLOW-DESIGN.md` 6절, `lib/common.js` (`validateRequest`, `normalizeAgentsOutput`, `maskPII`, `buildResponse`, `calcRefund`) | 필수·선택·타입·변환과 가린 WF-12 샘플(차단 전 과거 배포본) 기록, 11/07 현재 연결에 맞춰 수정, 로컬 공통·환불·연결 회귀 **39/39**, 응답 9개 필드 일치 | [x] |
| 5 | **RAG 아키텍처 설계서** (1/4) | 청킹 단위·오버랩·길이 분포와 선정 근거를 작성했다. | `docs/RAG-ARCHITECTURE.md` 1~2절, `workflows/ticketmoa-index.json` (`Validate and make chunks`) | `knowledge/*.md` 8개 문서 `##` 절 단위 청킹, 오버랩 0, **42개 청크** 길이 분포(최소 **116자** / 중앙값 **229자** / 최대 **432자**) 및 500/80 비교 실험 기록 | [x] |
| 6 | **RAG 아키텍처 설계서** (2/4) | 임베딩 모델 선정 이유와 실제 벡터 차원을 기록했다. | `docs/RAG-ARCHITECTURE.md` 3절, `ticketmoa-index` · `ticketmoa-search` (`text-embedding-3-large`) | OpenAI `text-embedding-3-large` 실제 벡터 차원 **3,072차원** 확인, 한국어 질문-문서 의미 검색 점수 분포 실측 | [x] |
| 7 | **RAG 아키텍처 설계서** (3/4) | 거리 계산 방식과 인덱스·메타데이터 구조를 작성했다. | `docs/RAG-ARCHITECTURE.md` 3~4절 (`ticketmoa_kb_v1_all` 37청크 · `ticketmoa_kb_v1_staff` 5청크, 메타데이터 `{doc, section, access_level}`) | Cosine Similarity 직접 재계산 대조 확인, `WF-05` 일반 고객 검색 시 스태프 문서 사전 필터링(노출 0건, 3/3 통과) 확인 | [x] |
| 8 | **RAG 아키텍처 설계서** (4/4) | 백업·복구 및 확장 방안을 작성했다. | `docs/RAG-ARCHITECTURE.md` 5절, `tools/reindex.py` | Git 원본 백업, 로컬 재색인 약 **5.9초(1회)**·비용 추산·10배 확장 기록. 최신 VM은 8/8·42청크 복구 확인, 경과 시간·롤백 시간은 미측정 | [x] |
| 9 | **워크플로우 실행 결과서** (1/4) | 주요 시나리오별 실행 테스트 로그가 있다. | `docs/EXECUTION-RESULT.md` 0~3절, 8절, `runs/*.json`, `runs/vm/*.json` | 최신 전체 회귀 T행(예열 뒤): 공통 **51/51**, 팀 **13/13**, 보안 **8/8**, bench 실패 **0/5**. S행(예열 없음) **50/51**, R행 **48/51**, O행 **50/51**·**11/13**, 과거 N행 **51/51**은 이력으로 보존 | [x] |
| 10 | **워크플로우 실행 결과서** (2/4) | 예외 상황의 실제 처리 결과가 있다. | `docs/EXECUTION-RESULT.md` 0.1~0.2절, 2.1~2.2절, 8절 | WF-03~13 예외 결과는 실행 시점별로 분리한다. T행 예외 39/39, WF-11은 실제 지연 경로를 지났다 | [x] |
| 11 | **워크플로우 실행 결과서** (3/4) | 기대 결과와 실제 결과를 구분했다. | `docs/EXECUTION-RESULT.md` 2.1~2.2절 시나리오별 비교 표 | 각 케이스의 `기대 판정 (expect)` 열과 로컬·팀 VM 실제 통과 여부·소요 시간·실제 반환 `route` 및 주요 필드를 분리 대조 | [x] |
| 12 | **워크플로우 실행 결과서** (4/4) | 실패 사례와 재시험 결과를 기록했다. | `docs/EXECUTION-RESULT.md` 4절 및 11/06 실행 판정 | 최신 T행 51/51(예열 뒤), 같은 워크플로우의 예열 없는 S행 50/51(WF-01 첫 호출 8.0초 실패). 차단 정책 시기 R행 48/51(WF-07 3건)과 복구 뒤 WF-07 3/3, 재요청 응답 복구 전 P행 40/51, O행 50/51(WF-01 9.0초), 과거 45/51·51/51, 재시작 직후 지연 및 장애 원인 미확인을 보존 | [x] |
| 13 | **공통** (1/3) | 세 설계서·결과서의 내용이 실제 구현과 일치한다. | `docs/WORKFLOW-DESIGN.md`, `docs/RAG-ARCHITECTURE.md`, `docs/EXECUTION-RESULT.md` | 11/07 대조: 워크플로우 10개 이름·웹훅 경로·메모리 키(`ticketmoa_kb_v1_all`/`staff`)·응답 계약 필드, 설계서 3.1절 그림, `README.md` 흐름은 일치. RAG 설계서 최종 대조가 남음 | [ ] |
| 14 | **공통** (2/3) | 예시 수치를 팀의 실제 측정값으로 교체했다. | 세 산출물 전체 표 및 본문 (`runs/` · `runs/vm/` 실측치 반영) | 템플릿 예시 수치를 모두 제거하고 로컬(`runs/`) 및 팀 VM(`runs/vm/`) 실측치·`reindex.py`·`/logs` 측정값으로 교체 완료 | [x] |
| 15 | **공통** (3/3) | 인증정보와 개인정보가 문서·로그·저장소에 노출되지 않았다. | n8n Credentials (`openAiCourse0001`, `ticketmoa-data-api`, `ticketmoa-team-key`), `lib/common.js` (`maskPII`) | 저장소 내 실제 API 키·토큰 0건, 가짜 연락처(`010-****-3307`) 마스킹 및 `/logs` 질문 원문·연락처 노출 0건 확인 | [x] |

---

## 2. 세부 기능별 실측 검증 표 (15개 핵심 기능)

| # | 기능별 검증 항목 | 구현 워크플로우 · 노드 | 검증 시나리오 | 로컬 및 팀 VM 실측 결과 (`runs/` · `runs/vm/`) | 충족 |
| :---: | --- | --- | --- | --- | :---: |
| 1 | **공통 Webhook 입구 및 Header Auth 인증**: `POST /webhook/ticketmoa-support` 단일 입구와 `X-Team-Key` Header Auth(`ticketmoa-team-key`) 적용, 공통 응답 9개 필드 준수 | `ticketmoa-support` · `Question webhook`, `Build response` | 전체 (WF-01~13, TM-01~13) | 로컬·팀 VM 전 케이스 응답 스키마 100% 일치 (`runs/vm/common-20261105-061255.json`) | ✔ |
| 2 | **입력 유효성 검증 (규칙)**: 빈 질문(`empty_question`), 미등록 사용자(`unknown_user`), 501자 이상(`question_too_long`) 요청 시 LLM 호출 전 HTTP 400 반환 | `ticketmoa-support` · `Get users` → `Check input` → `Reject invalid` | WF-13a, WF-13b, WF-13c | 로컬 **9 / 9**, 팀 VM **9 / 9 통과** (HTTP 400, 0.1~0.2s, `llm_calls: 0`) | ✔ |
| 3 | **프롬프트 주입(Injection) 및 반복·IP 사전 차단**: 주입 패턴(`rule`), 과도한 반복 요청(`rate_limit`), 해외·블랙리스트 IP(`geo`, `ip_blocklist`)를 LLM 호출 전 규칙으로 차단하고 정상 문의는 통과 | `ticketmoa-support` · `Injection rules`, `Check rate limit`, `Check IP policy` | WF-08, TM-04, TM-09~12 | WF-08 로컬 **3 / 3**·VM **3 / 3**, TM-04·TM-09~12 팀 VM(`ea1a6c9`) **5 / 5 통과** | ✔ |
| 4 | **업무 레지스트리 기반 Supervisor 분류 및 Fail-Closed**: `config/registry.json` 기반 Structured Output JSON 분류 및 파싱 실패·장애 시 `담당자 이관` 폴백 | `ticketmoa-support` · `Load registry`, `ticketmoa-agents` · `Supervisor 분류` | WF-01, WF-10, TM-01~08 | 정상 분류 및 LLM 장애 시 fail-closed 이관 확인 (VM B행 **51 / 51**, A행 **50 / 51**) | ✔ |
| 5 | **보완 질문 루프 및 반복 한도 이관**: 저신뢰(`confidence < 0.7`) 또는 필수 정보 누락 시 `보완 질문`(`attempt < 3`), `attempt >= 3`이면 LLM 호출 없이 즉시 `담당자 이관` | `ticketmoa-agents` · `LLM 필요?`, `ticketmoa-support` · `Plan route` | WF-02 (`attempt: 1`), WF-02b (`attempt: 3`) | WF-02 로컬 **3 / 3**·VM **3 / 3**, WF-02b 로컬 **3 / 3**·VM **3 / 3 통과** (`llm_calls: 0`) | ✔ |
| 6 | **문서 품질 검사 및 권한 분리 색인**: `knowledge/*.md` 8개 문서를 `##` 절 단위로 청킹하고 품질 검사 후 `ticketmoa_kb_v1_all`·`ticketmoa_kb_v1_staff`로 분리 저장 | `ticketmoa-index` · `Validate and make chunks`, `Store public/staff chunks` | `tools/reindex.py` | 문서 8/8 (일반 7, 스태프 1, 정제본 42청크), `issues: []`, `store_output_received` 확인 | ✔ |
| 7 | **공개 검색의 직원 문서 차단**: 로그인이 없어 공개 Search에서 직원 저장소 검색을 제공하지 않는다(11/07 리드 확정). 과거 access-level 필터링 결과는 당시 동작 이력이다. | `ticketmoa-search` · `검색 준비`, `빈 질문 결과` | 과거 WF-05; 현재 SEC-01·02 및 차단 정책 | 과거 WF-05 고객 검색 노출 0건 시험과 별도로, SEC-01·02 이름·access_level 조작 차단 **2/2 PASS 보고**. 직원 검색 정상 경로는 제공하지 않음 | ✔ (현재 공개 경로 차단 범위) |
| 8 | **근거 기반 RAG 답변 및 무근거 추측 금지**: 검색된 문서(`hits`) 범위 안에서만 답변과 `sources`를 작성하고, 지식 문서에 근거가 없는 질문은 `담당자 이관`(`sources: []`) 처리 | `ticketmoa-tech` · `답변 작성`, `작성 결과 검사` | WF-01, WF-03, TM-01, TM-07 | WF-03 로컬 **3 / 3**, 팀 VM **3 / 3 통과** (`route: "담당자 이관"`, `sources: []`, `writer_not_grounded`) | ✔ |
| 9 | **검증 Agent(Reviewer) 다중 점검**: 작성된 답변이 검색 근거(`hits`) 내에 있는지, 환불·취소 직접 실행 주장이 없는지, 개인정보가 없는지 검증하고 미통과 시 `담당자 이관` 처리 | `ticketmoa-tech` · `검증 호출` → `ticketmoa-agents` (`/webhook/ticketmoa-agents-verify`) | WF-01, WF-12, TM-01, TM-07 | 정상 답변 시 `llm_calls: 3`(분류+작성+검증)으로 검증 통과 확인 | ✔ |
| 10 | **본인 건 조회와 타인 건 거절**: 요청 `user`와 기록 `requester`가 일치할 때만 답하고, 다르면 `권한 없음`. 로그인이 없어 사칭은 막지 못한다. | `ticketmoa-payment`, `ticketmoa-support` | WF-06, WF-07, SEC-03·05·06·08 | T행 WF-06·07 각 **3/3**, SEC-03·05·06·08 통과(`runs/vm/tm-reg-security-permissions-20261107-094212.json`) | ✔ (사칭 제외) |
| 11 | **개인정보(PII) 마스킹 및 가림 개수 기록**: 응답 본문·티켓 요약·로그에서 전화번호와 이메일을 마스킹(`010-****-xxxx`, `x***@example.com`)하고 가린 개수를 `security.masked`에 기록 | `ticketmoa-payment`, `ticketmoa-support` · `maskPII` (`lib/common.js`) | WF-07, WF-12 | T행 WF-07 **3/3**, WF-12 **3/3**(`security.masked: 2`), 응답의 연락처 원문 0건 | ✔ |
| 12 | **환불 2단계 확인과 규칙 계산**: 1차 금액 안내, 2차 확정 뒤 환불 요청 티켓. 실제 취소는 상담원 | `ticketmoa-refund` | TM-02·03·06·13 | T행 TM-02·03·06·13 통과(단회) | ✔ |
| 13 | **복합·긴급 병렬 처리**: 대체 입장 근거 검색과 본인 문의 조회를 병렬로 합쳐 긴급 티켓과 현장 알림으로 이관 | `ticketmoa-support` · `Call search ∥`, `Call payment ∥`, `Merge search + lookup` | WF-12, SEC-07 | T행 WF-12 **3/3**(4.0 / 3.7 / 3.8초, `담당자 이관`). 차단 정책 시기 R행 3/3은 조회가 없는 경로라 합산하지 않는다 | ✔ |
| 14 | **외부 API·LLM 장애 격리, 선택적 재시도, 중복 방지, DLQ·알림**: 429·5xx·timeout만 재시도(401·403 제외), 티켓 API 장애 시 `ticket: null` + `/dlq` + `/alerts` 기록(HTTP 200 유지), `key=request_id`로 중복 티켓 방지(`duplicate: true`), `ticketmoa-errors` 구성 | `ticketmoa-handoff`, `ticketmoa-payment`, `ticketmoa-errors`, `ticketmoa-support` | WF-04, WF-09(1·2차), WF-10, WF-11 | T행 WF-04·09·10·11 **15/15**, WF-11은 8초 지연을 지나 5.6~5.7초에 이관. Error Workflow는 격리 n8n에서만 자동 실행 확인, 운영 Support 오류·운영 Discord 수신은 미검증 | ✔ (WF-04·09·10·11) · 운영 Error Workflow 미검증 |
| 15 | **비식별 실행 로그(`/logs`) 기록 및 비밀키 분리**: 응답 직전 `POST /logs`에 비식별 지표만 기록(질문 원문·연락처 제외)하고 저장소 내 API 키·토큰 노출 0건 유지 | `ticketmoa-support` · `Log record` → `POST /logs`, n8n Credentials | `/logs?source=live` (120건), `flow.py check` | `/logs` 120건 원문·PII 노출 0건 확인, Credential 고정 ID 사용 확인 | ✔ |
