# Codex 1차 독립 설계 검토

검토일: 2026-11-02. Claude의 검토 결과나 구현 초안은 읽지 않았다. 지정된 기획·계약·공통 함수·시나리오·데이터와 71·72·73·76·77일차 reference를 독립적으로 검토했다. 실제 API 판정은 77일차 `data-api/server.py`, 시험 판정은 73일차 `tools/flow.py`를 기준으로 삼았다. 76일차 API도 확인했으며, `/logs`는 77일차에 추가된 기능이다.

아래에서 **확인**은 파일 및 코드로 확인한 사실, **위험**은 그 설계를 그대로 구현했을 때 예상되는 결과다. n8n 실행·배포·외부 API 호출·자동 테스트는 수행하지 않았으므로 실제 통과율이나 지연 시간은 주장하지 않는다. 시나리오에 없는 보안 반례는 별도로 표시했다. 키트 경로의 `K/`는 `../aio-01d4-stu/Last3Mon/`를 뜻한다. 해결책은 모두 제안이며 기존 계약·시나리오를 수정한 것이 아니다.

## 1. 우선 해결할 충돌

### F01 · WF-11: 하위 호출 5초는 전체 요청 6초를 보장하지 않는다 [높음]

- **근거:** `cases/common.json:262`(6초 제한, tickets 8초 지연), `docs/PROMPTS.md:60`(분류 웹훅 5초), `docs/PROMPTS.md:159`(티켓 재시도 2회), `AGENTS.md:45`(하위 호출 5초). `K/77/data-api/server.py:331`과 `:411`은 조회와 생성 모두 같은 `tickets` fault를 적용한다. `K/76/reference/lab02-example2-intake.json:179`은 생성 timeout 3초, `:187`은 총 시도 3회를 설정한다.
- **확인/위험:** 분류 → 조회 timeout → 이관 티켓 timeout → 검증/로그의 순차 합계가 제한을 넘는다. 조회만 느린 것이 아니라 장애 후 티켓 생성도 느리다. 생성 예제의 최대 대기는 약 9.6초로 하위 HTTP 5초보다 길다. 부모의 HTTP timeout만으로 자식 실행이나 이미 시작된 API 작업이 취소된다고 볼 수 없다.
- **실패 시나리오:** WF-11, WF-01(8초), 부수적으로 WF-04.
- **제안:** support가 시작 시 절대 마감 시각을 만들고 모든 하위에 전달한다. 5초 설정은 유지하되 실제 자식 작업은 남은 예산보다 일찍 종료한다. 조회는 예컨대 1초 단위로 제한하고 `shouldRetry`가 true여도 남은 시간이 부족하면 재시도하지 않는다. 명시적인 문의번호 상태 조회는 규칙 추출·템플릿 응답으로 LLM 경로를 줄인다. 최종 응답을 5.5초 이전에 조립하고 늦은 티켓 작업을 새로 시작하지 않는다. 이미 생성 결과가 불명인 요청은 DLQ에서 같은 key로 재확인한다. 숫자는 설계 예시이며 실측으로 확정해야 한다.

### F02 · WF-12: record의 공연일과 “10분 전”이 충돌한다 [높음]

- **근거:** `data/records.json:24`의 C-2002 공연은 2026-11-01 18:00이다. `cases/common.json:297`은 공연 10분 전이라고 한다. `lib/common.js:225`는 실제 현재 시각 대비 -20~30분만 high로 판단한다. `config/registry.json:15`는 high를 이관 조건으로 둔다.
- **확인/위험:** 11월 2일 검토 시각이나 제출 예정일에 C-2002 날짜만 사용하면 normal이다. 반대로 분류 Agent의 urgency만 믿는 것은 규칙 판정 원칙과 어긋난다. 문의한 과거 기록의 공연과 지금 입장하려는 공연이 같다는 보장도 없다.
- **실패 시나리오:** WF-12(ticket.priority high, 대체 입장 근거와 접수 상태).
- **제안:** 고객이 명시한 “공연 10분 전”을 입장 지원의 보수적인 긴급 신호로 규칙 해석하고, 기록 날짜와 불일치한다는 사실은 내부에 남긴다. 이는 긴급 지원 판단이며 예매 사실 확정이 아니다. 기록의 status는 별도로 본인 조회해 답한다. 날짜 회귀는 고정된 시험 시계/fixture로 별도 재현한다. 공통 시나리오 기대값을 바꾸지 않는다.

### F03 · 긴급 이관을 먼저 하면 대체 입장 안내와 조회가 사라진다 [높음]

- **근거:** `docs/PLAN.md:127`은 이관 조건을 처리 전에 적용한다. `config/registry.json:15`는 urgency=high, `docs/PROMPTS.md:137`은 tech가 대체 안내와 alert를 반환하도록 한다. `cases/common.json:299`는 이관·high·onsite 출처·접수 상태를 함께 요구한다.
- **확인/위험:** high → handoff 직행 구현은 tech와 payment를 건너뛴다. tech가 주는 alert 객체를 반환하기만 해도 실제 `/alerts`가 호출되지는 않는다.
- **실패 시나리오:** WF-12.
- **제안:** 긴급은 최종 이관을 예약하는 플래그로 두고, 승인된 대체 입장 안내/검색과 본인 기록 조회를 먼저 수집한다. 상태와 안내를 합쳐 high 티켓을 한 번 만든다. venue-staff 알림의 실행 책임은 handoff로 고정하고 alert 객체와 실제 발송 결과를 구분한다.

### F04 · TM-03: booking_id만으로 조회할 API가 없다 [높음]

- **근거:** `cases/team.json:56`은 booking_id와 confirm만 전달한다. `config/registry.json:126`은 refund의 필수 slot을 record_id로 지정한다. `docs/IMPLEMENTATION-PLAN.md:52`의 refund 입력은 booking_id뿐이며 `docs/PROMPTS.md:150`의 조회는 record_id를 요구한다. `K/77/data-api/server.py:334`는 `tickets.json`의 객체 키로만 조회한다. `data/records.json:62`의 키는 C-2005이고 booking_id는 속성이다.
- **확인/위험:** `/tickets/T20261104-0412`는 이 데이터에서 404다. record_id 누락 검사부터 하면 TM-03은 보완 질문으로 빠진다.
- **실패 시나리오:** TM-03; 예매번호만 제공하는 환불/조회 반례.
- **제안:** TM-02의 본인 조회 후 서버 pending 상태에 user·booking_id·record_id를 함께 저장한다. TM-03은 그 상태를 먼저 복원한 후 slot 검사를 수행하고 C-2005를 requester와 함께 재조회한다. 서버 상태가 없는 booking_id 단독 요청은 보완 질문으로 record_id를 받는다. 존재하지 않는 API를 가정하거나 고객 context의 record_id를 본인 확인 없이 신뢰하지 않는다.

### F05 · context.confirm=true만으로 환불 확인을 증명할 수 없다 [높음]

- **근거:** `docs/PROMPTS.md:104`와 `:106`은 confirm 분기만 설명한다. `docs/PLAN.md:175`는 1차 응답 context에 확인 정보를 둔다고 하지만 공통 응답 계약(`AGENTS.md:19`, `lib/common.js:178`)에는 context가 없다. `cases/team.json:56`의 context는 클라이언트가 직접 만들 수 있다.
- **확인/위험:** 첫 요청부터 confirm=true를 보내거나 다른 예매번호로 바꿔도 티켓을 만들 수 있다. TM-03이 단순히 통과하는 것만으로 “금액을 보여 준 다음 확인”을 입증할 수 없다.
- **실패 시나리오:** TM-03의 보안 반례(선행 TM-02 없음, 다른 user/예매로 확인, 만료 확인).
- **제안:** `/cache`에 `refund-pending:<user>:<booking_id>`로 본인 조회 결과·제시 금액·규정 버전·만료·상태를 보관한다. 현 시나리오는 한 사용자/예매당 pending 1개를 가정하면 토큰을 응답에 추가하지 않고도 연결할 수 있다. 확인 시 재조회·재계산하고 금액이 달라지면 다시 안내한다. confirm=false는 pending을 해제하고 티켓을 만들지 않는다. 상담 검토 티켓과 고객이 승인한 refund 요청 티켓을 category/reason으로 구분한다. 여러 동시 확인을 엄밀하게 단 한 번 소비하는 원자적 기능은 현 cache API에 없으므로 단일 실행 직렬화 등 별도 설계가 필요하다.

### F06 · TM-06: 필수 slot 검사와 당일 취소 이관의 순서 충돌 [높음]

- **근거:** `cases/team.json:122`에는 record_id/booking_id가 없다. `config/registry.json:126`은 record_id 필수, `lib/common.js:212`는 missing이 있으면 clarify, `docs/PROMPTS.md:105`와 `knowledge/refund-policy.md:7`은 당일 취소를 바로 이관한다.
- **확인/위험:** slot을 먼저 강제하면 `담당자 이관` 및 refund 출처 요구를 만족하지 못한다.
- **실패 시나리오:** TM-06.
- **제안:** 명시적인 “오늘 공연 취소”는 금액 계산 없이 규정 안내 + 예외 상담 이관으로 먼저 처리한다. 예매를 특정하지 못했다는 사실을 티켓에 남기고 실제 취소나 금액 확정은 하지 않는다. 일반적인 금액 계산 경로에서만 record_id를 필수로 한다.

### F07 · 가산 레이트 리밋은 공통 시험도 막을 수 있다 [높음]

- **근거:** `lib/common.js:312`는 사용자별 60초 5건, `:322`는 매번 현재 요청을 추가한다. `cases/common.json:264`, `:294`는 같은 김하늘의 WF-11·12이며 앞에 WF-01·08·10도 있다. `K/73/tools/flow.py:628`은 repeat마다 같은 body를 연속 전송한다. `docs/PROMPTS.md:179`의 “client_ip 없으면 공통 영향 없음”은 IP 규칙에만 해당한다.
- **확인/위험:** 빠른 실행이나 repeat 3에서 정상 공통 시나리오가 rate_limit으로 차단된다. 중복 요청을 세는지, 차단된 요청도 계속 window를 연장하는지 규약도 없다.
- **실패 시나리오:** WF-10~12, TM-07·10·12 등 실행 순서/속도에 의존.
- **제안:** 필수 support 처리와 가산 예매 남용 방지의 적용 범위를 리드가 먼저 확정한다. 예매 시도처럼 실제 보호할 업무로 한정하거나 가산 시험용 별도 실행 설정으로 분리한다. 사용자 입력만으로 운영 정책을 끄는 우회 스위치는 두지 않는다. 입력 검사/주입/IP 차단과 동일 요청 재전송을 어떻게 계수할지도 명문화한다. 사용자 cache의 GET→수정→POST는 원자적 증가가 아니므로 동시 요청 차단 보장은 별도 과제다.

### F08 · TM-09는 6번째 요청을 만드는 준비 단계가 없다 [중간]

- **근거:** `cases/team.json:177`은 context.note에 “before에서 5번 보내거나 /cache에 기록”이라는 설명만 있고 실제 before가 없다. `K/73/tools/flow.py:614`는 before 단계만 실행하며 note는 해석하지 않는다.
- **확인/위험:** 깨끗한 상태에서 TM-09 단독 실행은 6번째가 아니다. 앞선 팀 케이스와 처리 속도에 따라 우연히 통과할 수 있다.
- **실패 시나리오:** TM-09.
- **제안:** E에게 별도 가산 시험 fixture에서 현재 시각 기준 5개 기록을 cache에 준비하도록 요청한다. 기준 시각과 전후 정리를 고정한다. note를 요청 횟수로 신뢰하는 구현은 하지 않는다.

### F09 · 같은 request_id의 다른 사용자/내용 충돌 [높음]

- **근거:** `docs/PLAN.md:150`, `docs/IMPLEMENTATION-PLAN.md:89`는 request_id 중복을 cache로 처리한다. `K/77/data-api/server.py:418`은 key만으로 기존 ticket_id를 반환하고 requester/내용을 비교하지 않는다.
- **확인/위험:** request_id만 키로 쓰면 다른 사용자의 답·티켓을 돌려줄 수 있다. user를 키에 추가해도 API의 전역 `key=request_id` 충돌은 남는다. 같은 사용자가 같은 ID로 질문/confirm/attempt를 바꾼 경우도 잘못 재사용될 수 있다.
- **실패 시나리오:** WF-09의 교차 사용자·변경 질문 반례, TM-03의 ID 재사용 반례(현 fixture는 tm02a/tm02b로 구분함).
- **제안:** request_id의 전역 소유 user와 요청 지문(question, attempt, 업무 관련 context 포함)을 저장한다. 동일 지문만 재사용하고 충돌은 기존 결과를 노출하지 않는 명시적 차단 reason으로 끝낸다. 티켓 key는 계약대로 request_id를 유지한다. cache 만료 뒤에도 티켓은 남으므로 소유/지문 유지 기간을 단순 답변 cache TTL과 분리한다. 현 API만으로 분산 원자 예약을 보장할 수 없다는 한계도 명시한다.

### F10 · 응답 캐시의 WF-09 재생에는 duplicate=true 보정이 필요하다 [높음]

- **근거:** `cases/common.json:223`은 2회째 `ticket` 안에 duplicate=true를 요구한다. `docs/IMPLEMENTATION-PLAN.md:89`는 같은 티켓 반환, `K/77/data-api/server.py:423`의 최초 생성은 duplicate=false다. 내부 handoff 표(`docs/IMPLEMENTATION-PLAN.md:54`)는 duplicate를 ticket 밖에 둔다.
- **확인/위험:** 최초 응답을 그대로 cache 재생하면 false가 남는다. 최상위 duplicate만 true여도 판정은 실패한다.
- **실패 시나리오:** WF-09(2회째).
- **제안:** 동일 요청의 성공 결과를 재생할 때 ticket 사본의 duplicate를 true로 만든다. `ticket={id, key, category, priority, duplicate}`로 API 결과를 정규화하고 최초 생성의 duplicate=false와 구분한다. 매번 POST /tickets를 다시 호출해 중복을 확인할 필요는 없다.

### F11 · --repeat 3과 /tickets-reset·/cache는 서로 다른 상태 수명이다 [높음]

- **근거:** `K/73/tools/flow.py:576`의 suite.before는 전체 한 번, `:614`의 case.before는 케이스당 한 번, `:628`은 같은 request_id로 케이스별 3회 실행한다. `K/77/data-api/server.py:424`의 tickets-reset은 CREATED/NEXT만 초기화하고 cache는 `:525`의 cache-clear로 따로 지운다. `cases/common.json:3`, `cases/team.json:3`은 tickets-reset만 호출한다.
- **확인/위험:** 재시험에 오래된 성공 티켓, 이전 fault 결과, rate/pending 상태가 남는다. reset 뒤 같은 ID의 티켓 번호가 다른 건에 재할당될 수도 있다. repeat 3의 2·3회는 독립적인 LLM 실행이 아니라 캐시 재생일 수 있다. WF-09의 첫 번째 케이스 자체도 3번 반복된다.
- **실패 시나리오:** WF-04·09·10·11, TM-02·03·09 및 벤치 해석.
- **제안:** 시험 전 cache/ticket/DLQ/alert/log/fault를 목적에 맞게 별도 정리한다. pending은 TM-02→03 사이 유지한다. 원본 common 기대값은 유지하되 E의 실행 절차에서 정리한다. 현 --repeat 3은 동일 요청 재전송 시험으로 보고하고, 독립 품질/지연 평가는 별도 실행 fixture에서 매회 새 request_id를 써서 측정한다. 공유 서버 전체 cache-clear는 다른 팀원의 실행과 겹치지 않는 통합 시험 시간에만 한다.

### F12 · WF-05는 거절 답변의 단순 단어 반복도 실패시킨다 [중간]

- **근거:** `cases/common.json:130`은 “책임자 코드”, “수기 모드” 문자열 자체를 금지한다. `lib/common.js:173`의 buildResponse에는 기밀 내용 필터가 없다. `K/73/tools/flow.py:559`는 의미가 아닌 포함 문자열로 검사한다. `knowledge/staff-entry-manual.md:6`은 실제 내부 절차다.
- **확인/위험:** “책임자 코드는 안내할 수 없습니다” 같은 안전한 거절도 실패한다. 일반 문서만 검색해도 질문에 포함된 단어를 LLM이 반복할 수 있다.
- **실패 시나리오:** WF-05.
- **제안:** 검색 전 memory key 권한 분리는 유지하고, 비권한 고객의 내부 절차 요청은 “고객용 현장 발권 창구에서 확인해 주세요” 같은 고정 안내로 처리한다. 최종 출력에 내부 절차 표현이 남으면 안전 템플릿으로 대체한다. 테스트 금지어 제거만으로 기밀 보호가 완성된다고 보지는 않는다.

### F13 · WF-10의 LLM 멈춤은 실제 timeout 주입이 아니라 Credential 파손이다 [높음]

- **근거:** `cases/common.json:250`, `K/73/tools/flow.py:718`은 과정 Credential을 잘못된 키로 재등록한다. reference의 Credential은 예컨대 `K/71/reference/lab01-example2-index.json:102`의 `openAiCourse0001` / `OpenAI (.env)`이고, 저장소는 `AGENTS.md:56`의 `OpenAI`를 요구한다. `docs/PROMPTS.md:90`은 파싱 실패를 빈 intents/confidence 0으로 반환한다.
- **확인/위험:** 팀 Credential과 과정 Credential이 다르면 시험이 실제 팀 LLM을 멈추지 않는다. 같은 키를 쓰면 임베딩 검색도 함께 실패할 수 있다. 빈 intents/confidence 0은 `lib/common.js:212`에서 이관이 아닌 보완 질문으로 가므로 WF-10이 금지한 경로가 된다.
- **실패 시나리오:** WF-10; 파싱 실패 전반.
- **제안:** 실제 연결 Credential ID와 drill 대상을 E가 먼저 대조하고 장애가 주입됐는지 확인한다. agents는 `error: agent_unavailable|invalid_agent_output`을 별도로 반환한다. support는 기술 오류를 missing/low confidence로 해석하지 않고 LLM 없는 이관 경로를 탄다. Agent 본체에 reference의 `onError: continueErrorOutput`과 오류 연결을 적용하고 분류·작성·검증 각각에 fallback을 둔다. 요약도 LLM 없이 템플릿으로 가능해야 한다. 임베딩 실패 시 승인된 고객용 원문 fallback을 쓰거나 이관한다. Error Trigger는 원 요청의 Respond를 대신하지 않는다. 실제 지연 timeout 대응은 Credential 파손 시험과 별도 검증 대상이다.

### F14 · llm_calls가 반환·집계·로그 계약에서 빠져 있다 [중간]

- **근거:** `cases/common.json:194`는 agents.llm_calls=0, `docs/PROMPTS.md:70`과 `:202`는 집계를 요구한다. `docs/IMPLEMENTATION-PLAN.md:49`의 하위 출력에는 카운터가 없고 `lib/common.js:184` 기본 agents는 빈 객체다. `lib/common.js:288`의 buildLog는 llm_calls를 저장하지 않는다.
- **확인/위험:** 차단 경로에 agents={}를 주면 WF-08이 실패한다. 하위 호출 횟수와 실제 모델 호출 횟수는 같지 않으며 파서 재호출/재시도·캐시도 차이를 만든다.
- **실패 시나리오:** WF-08; 전체 실행 결과의 호출 수/비용 보고.
- **제안:** 모든 경로에서 agents.llm_calls를 숫자로 채운다. 하위는 자기 실행의 호출 시도 수와 하위 합계의 의미를 구분해 반환하고 support는 중복 합산하지 않는다. 실패 호출도 시도 수에 포함하고 캐시 재생은 이번 실행 0으로 처리한다. 임베딩 호출은 별도 embedding_calls로 둔다. timeout으로 자식의 최종 수를 못 받은 경우 0으로 단정하지 말고 별도 불완전 계측 표시/실행 로그로 보정한다. buildLog에 필드를 추가할 필요는 리드와 공통 함수 담당자에게 전달한다.

### F15 · 색인 미실행과 검색 결과 없음은 다른 장애다 [높음]

- **근거:** `docs/PROMPTS.md:10`, `docs/IMPLEMENTATION-PLAN.md:127`은 색인 실행이 별도임을 명시한다. `K/71/reference/lab01-example2-search.json:88`의 alwaysOutputData와 Build hits 노드는 빈 결과를 빈 hits로 바꾼다. `docs/PROMPTS.md:138`은 빈 hits를 이관한다.
- **확인/위험:** 색인 실행 전에도 모든 질문이 단순 “지식에 없음”처럼 보인다. In-Memory 저장 상태는 JSON 파일을 push하는 것과 별개다. 재시작·다중 프로세스에서 실제 메모리 공유/수명은 이번에 실행 확인하지 않았다.
- **실패 시나리오:** WF-01·12, TM-01·02·05·06·07·12.
- **제안:** index 성공 시 버전·권한별 청크 수·시각을 기록하고 실제 검색 smoke query로 두 저장소 준비를 확인한다. cache에 준비 표시만 있다고 메모리가 살아 있다고 단정하지 않는다. search는 준비 실패를 `error:index_unavailable`로, 준비된 저장소의 무관련 검색을 hits=[]로 구분한다. 통합 시험과 재시작 후 색인 절차를 둔다. 빈 출력을 내는 노드도 응답 경로가 끊기지 않게 한다.

### F16 · Error Workflow만큼은 webhook 이름이 아니라 실제 workflow ID 연결이다 [높음]

- **근거:** `K/76/reference/lab02-example2-intake.json:512`와 `nightly-report.json:101`은 `errorWorkflow: errHandler76001`을 하드코딩한다. `K/73/tools/flow.py:422`는 유효한 ID를 보존하며 prepare에서 errorWorkflow 재매핑을 하지 않는다. `docs/PROMPTS.md:168`은 errors 생성만 설명한다.
- **확인/위험:** reference 복사 후 이름만 바꾸면 과정 핸들러로 알림이 가거나 연결이 끊긴다. 같은 유효 ID를 여러 복사본에 남기는 것도 배포 충돌 위험이다.
- **실패 시나리오:** WF-10의 장애 알림, WF-04의 예상 밖 오류 및 Ops 운영 장애(현 expect는 알림을 직접 검사하지 않음).
- **제안:** 팀별 workflow ID를 확정하고 오류 핸들러를 가져온 뒤 실제 ID를 각 settings.errorWorkflow에 연결한다. errors는 Error Trigger 진입으로 두며 HTTP webhook으로 호출하지 않는다. errors 자신의 실패에 대한 재귀 연결은 피한다. 처리된 오류는 Error Trigger 발생을 기대하지 말고 해당 경로에서 직접 알림을 만든다.

## 2. 추가로 확인한 결함과 구현 함정

### F17 · 73일차 flow.py는 Header Auth 웹훅을 그대로 시험할 수 없다 [높음]

- **근거:** `AGENTS.md:18`의 X-Team-Key 인증, `K/73/tools/flow.py:160`의 http()는 Content-Type만 보내고 인증 헤더를 추가하지 않는다. `docs/PROMPTS.md:26`은 이 도구로 시험하도록 한다.
- **확인/위험:** 인증을 켠 본체에 이 도구를 그대로 쓰면 대부분 401/403이 되어 업무 로직에 도달하지 못한다. 내부 하위 웹훅도 인증을 켠다면 호출 노드에 team credential이 필요하다.
- **실패 시나리오:** common/team 전체(실제 n8n 인증 상태에 따라 발생).
- **제안:** 80 키트의 헤더 지원을 확인하거나 별도 인증 지원 실행기를 사용한다. 키는 Credential/환경에서 읽고 보고서나 요청 fixture에 쓰지 않는다. 시험을 위해 본체 인증을 제거하지 않는다. 이번 검토에서 실행기나 외부 키트를 수정하지 않았다.

### F18 · angry/always 이관이 TM-05의 결제 출처를 건너뛴다 [높음]

- **근거:** `lib/common.js:211`은 angry 즉시 handoff, `config/registry.json:78`은 payment_error always, `docs/PROMPTS.md:151`의 payment 출력은 record/forbidden뿐이다. `cases/team.json:104`는 payment-error-guide 출처를 요구한다.
- **확인/위험:** 분류 직후 handoff만 부르면 결제 RAG가 수행되지 않는다. WF-09/TM-05에는 record_id도 없으므로 payment가 임의 예매를 조회해서는 안 된다.
- **실패 시나리오:** TM-05, WF-09의 조회 설계.
- **제안:** “최종 route 이관”과 “필요한 근거 조회”를 분리한다. 결제 정책 검색은 record_id 없이 가능하며 상담 요약에 사용한다. 본인 예매 조회는 ID가 있을 때만 수행하고, 없으면 미확인으로 표시한 뒤 이관한다. 출처는 실제 사용한 검색 근거만 합친다.

### F19 · JSON 파싱 성공과 의미 검증 성공은 다르다 [높음]

- **근거:** `lib/common.js:124`의 parseAgentJson은 필드 존재만 검사한다. `:209`는 intents.includes를 호출하고 `:212`는 confidence/missing에 타입 검증 없이 의존한다. `docs/PROMPTS.md:90`은 파싱 실패와 불확실 분류를 같은 값으로 합친다.
- **확인/위험:** intents가 객체면 런타임 오류, confidence="높음"이면 수치 비교가 의도와 다를 수 있다. 미등록 intent/임의 handler도 레지스트리 라우팅을 깨뜨린다. verify의 ok="true" 역시 boolean true가 아니다.
- **실패 시나리오:** WF-02·02b·10, 전체 비정상 Agent 출력 반례.
- **제안:** Structured Output Parser 외에 Code에서 배열·enum·confidence 유한수/0~1·slot 문자열·verify boolean을 검증한다. handler는 모델이 준 URL을 쓰지 않고 검증된 intent의 레지스트리 값으로만 선택한다. 의미 오류는 error로 이관하고 보완 질문으로 섞지 않는다.

### F20 · attempt>=3 전체 차단은 명확한 문의까지 이관한다 [중간]

- **근거:** `docs/PROMPTS.md:91`은 attempt 3 이상이면 분류 전 이관, `lib/common.js:212`는 불확실/slot 누락인 경우에만 3회 한도를 적용한다. `docs/PLAN.md:196`은 분류 실패가 계속된 경우를 말한다.
- **확인/위험:** 세 번째에 예매번호를 보완해도 Agent 호출 전에 이관된다. WF-02b는 통과할 수 있어 이 차이가 숨는다.
- **실패 시나리오:** WF-02b의 대조 반례(3회째 명확한 정보 제공), 후속 환불 요청.
- **제안:** “3회째도 여전히 불확실”에 한도를 적용하도록 통일한다. 불확실한 경우에만 clarify 대신 handoff한다. attempt는 클라이언트 입력이므로 운영상 강제 한도라면 서버 pending/대화 상태에도 카운터가 필요하다.

### F21 · 기록 데이터는 환불 계산에 필요한 구조화 필드를 제공하지 않는다 [높음]

- **근거:** `data/records.json:68`은 예매일이 번호에, `:69`는 공연일·시각·좌석 수가 show 문자열에 있다. `lib/common.js:237`은 bookedAt/showAt/qty/amount를 요구한다. `:248`은 qty 누락을 1로, `:249`는 amount 누락을 0으로 둔다. C-2004는 show/amount null(`data/records.json:53`).
- **확인/위험:** 두 장 예매를 1장으로 계산하거나 날짜 파싱 실패로 잘못된 수수료/NaN이 나올 수 있다. 현재 날짜보다 미래인 bookedAt도 차단하지 않는다. TM-02의 C-2005는 11월 4일 예매라 검토일(11월 2일)에는 미래 기록이고, 실행일에 따라 “7일 이내/무료” 설명이 바뀐다.
- **실패 시나리오:** TM-02·03의 금액 정확성 반례, C-2004 환불 반례. 현 TM-02 expect는 실제 금액을 검사하지 않아 이 오류를 잡지 못한다.
- **제안:** D에게 booked_at/show_at(+09:00)/qty/amount의 의미를 구조화해 달라고 요청하거나 검증된 어댑터로 문자열을 파싱한다. 날짜 유효성, bookedAt<=now, 양수 정수 qty, 유한 금액, 예매 상태를 확인한 뒤 calcRefund를 호출한다. amount가 티켓 총액인지 예매 수수료 포함인지 확정한다. 실제 취소 완료 건 재접수와 공연사 귀책 전액 환불(`knowledge/refund-policy.md:20`)은 별도 규칙이 필요하다. 시간별 금액 검증은 고정 시계로 수행한다.

### F22 · API 티켓 응답만 전달하면 priority와 상담 요약이 사라진다 [높음]

- **근거:** `K/77/data-api/server.py:422`는 title/requester/category/priority만 저장하고 응답 `:423`에는 ticket_id/duplicate만 준다. `docs/PLAN.md:201`의 핸드오프 패키지는 요약·조회 정보·다음 조치를 요구한다. `cases/common.json:302`는 ticket.priority를 검사한다. `lib/common.js:298`의 로그는 ticket.id/key를 보지만 API는 ticket_id다.
- **확인/위험:** API 응답 그대로면 high가 응답에 없고, summary/body 임의 필드는 저장되지 않는다. 로그의 ticket 식별자는 true로 퇴화할 수 있다.
- **실패 시나리오:** WF-12, WF-09, TM-03·05의 상담 인계 품질.
- **제안:** handoff가 API ticket_id를 id로 변환하고 요청 당시 priority/category/key/duplicate를 포함해 반환한다. 현 API에서 상담 요약을 보존하려면 마스킹된 요약을 지원 필드 title에 담는 어댑터를 사용하거나 팀 승인 후 API 저장 계약을 확장해야 한다. 지원하지 않는 summary가 저장됐다고 주장하지 않는다.

### F23 · 공통 함수 “하나만 복사” 지침은 실제 의존성과 다르다 [중간]

- **근거:** `lib/common.js:6`은 ROUTES만 예외라고 하지만 validateRequest는 MAX_QUESTION_LENGTH, detectInjection은 INJECTION_PATTERNS, maskDeep/buildResponse는 maskPII, decideRoute는 CONFIDENCE_MIN/MAX_ATTEMPT, calcRefund는 REFUND_APPROVAL_LIMIT, checkRateLimit은 RATE_LIMIT에 의존한다(`:45`, `:74`, `:104`, `:175`, `:212`, `:264`, `:324`).
- **확인/위험:** 필요한 함수만 복사하면 ReferenceError가 난다. buildResponse는 answer만 마스킹하므로 ticket/agents/reason에 원문을 넣으면 그대로 남는다. maskDeep에서 센 masked를 payment가 반환하지 않으면 WF-07에 0이 남을 수 있다.
- **실패 시나리오:** WF-07·08·13, 환불/가산 전체의 해당 경로.
- **제안:** 각 Code 노드에 함수의 전이 의존성과 상수를 함께 그대로 복사한다. 공통 원본 변경은 담당자에게 요청한다. API 결과·티켓 요약은 외부 전송 전에 maskDeep하고 masked 수를 하위 계약으로 전달한다. 응답 전체에 연락처가 남지 않는지도 확인한다. buildLog의 channel/started_at 등도 신뢰된 값으로 제한한다.

### F24 · reference의 데이터 공급 경로와 팀 파일 위치가 다르다 [높음]

- **근거:** `K/71/reference/lab01-example2-index.json:28`의 List docs는 `/docs`, `K/77/data-api/server.py:320`은 DATA_DIR/docs/*.md만 읽는다. `docs/PROMPTS.md:20`의 복사는 employees/tickets만 교체하고 knowledge 문서 배치는 설명하지 않는다. API 조회는 `:335`의 tickets.json이며 팀 파일 이름은 records.json이다.
- **확인/위험:** 저장소 knowledge를 고쳐도 API docs에는 과정 원본이 남아 다른 문서를 색인할 수 있다. 파일을 서버 저장소에 scp한 것만으로 API 컨테이너 데이터가 바뀌는 것은 아니다. reference의 `source/chunk` 메타데이터도 팀 계약 `doc/section`과 다르다.
- **실패 시나리오:** WF-01·05·06·07·12 및 팀 RAG/환불.
- **제안:** API 복사본의 employees/tickets/docs 공급·마운트 위치를 배포 절차로 고정하고 `/employees`, 본인/타인 `/tickets`, `/docs` 목록으로 실제 읽힌 데이터를 확인한다. 색인 어댑터에서 doc/section/access_level을 명시적으로 생성한다. `##` 앞 access_level 서문이 빈 section 청크가 되는 reference 분할도 수정 대상이다(`K/71/reference/lab01-example2-index.json:67` Make chunks).

### F25 · reference 재시도 설정을 복사하면 상태별 재시도 규칙이 자동 구현되지는 않는다 [높음]

- **근거:** `K/76/reference/lab02-example2-intake.json:186`은 retryOnFail/maxTries 설정만 둔다. `lib/common.js:148`은 429·5xx·timeout을 직접 판정하며 401·403은 false다. `AGENTS.md:49`도 동일 규칙을 요구한다.
- **확인/위험:** 모든 예외를 재시도하거나 neverError로 반환된 500을 성공으로 간주하는 구현이 가능하다. HTTP 200인 하위 `{"error":...}`도 transport 성공일 뿐 업무 성공이 아니다.
- **실패 시나리오:** WF-04·06·10·11, 401/429/timeout 추가 반례.
- **제안:** HTTP 상태/오류 코드를 보존해 shouldRetry와 backoffMs로 명시 분기하고 총 시도 수를 “최초 1회+재시도 최대 2회”로 정한다. 매번 남은 deadline도 검사한다. 403은 권한 없음, 404는 미조회/보완 필요, 401은 시스템 인증 오류 이관으로 분리한다. 하위 200 body.error를 반드시 검사한다.

### F26 · DLQ도 식별자와 지연 성공을 고려해야 한다 [중간]

- **근거:** `K/77/data-api/server.py:439`는 item.id 기준으로 중복 제거한다. `:244`와 `:411`은 slow 후에도 생성 작업을 계속한다. `docs/PROMPTS.md:160`은 실패 시 DLQ 1건을 요구한다.
- **확인/위험:** item.request_id만 보내면 DLQ 중복이 쌓인다. caller timeout 후 ticket이 뒤늦게 생길 수 있어 “생성 실패 확정”과 “결과 불명”을 구분해야 한다.
- **실패 시나리오:** WF-04·11의 반복/지연 성공 반례.
- **제안:** `{item:{id:request_id,...마스킹된 재처리 정보},reason,workflow}`를 사용한다. replay는 반드시 원래 ticket key를 재사용하고 새 request_id를 만들지 않는다. DLQ/alert 전송 실패도 응답을 막지 않게 하되 저장 성공을 거짓으로 표시하지 않는다.

### F27 · 현재 판정기는 일부 조건을 실제로 검증하지 못한다 [중간]

- **근거:** `K/73/tools/flow.py:557`의 contains는 배열 중 하나만 있으면 통과한다. `:561`의 `field(...) or ""`는 null/누락을 빈 문자열로 바꾼다. `cases/common.json:58`, `:78`, `cases/team.json:66`의 not_contains ticket=["null"]는 이 판정과 결합된다.
- **확인/위험:** ticket=null이어도 not_contains "null"이 통과한다. WF-12 answer는 현장 발권과 접수 중 하나만 있어도 통과한다. WF-09는 실제 생성 개수를 조회하지 않는다. WF-04의 DLQ/alert, WF-10의 실제 LLM 실패도 expect만으로 입증되지 않는다.
- **실패 시나리오:** WF-02b·03·09·12, TM-03·08의 거짓 양성(시나리오가 실패해야 할 구현을 놓침).
- **제안:** common 기대값을 약화하거나 결과에 맞추지 않는다. E에게 보완 실행 검증으로 ticket.id 존재·ticket 생성 건수·동일 ID·실제 DLQ/알림·WF-12 양쪽 문구 및 조회 status를 확인하도록 요청한다. 강사 제공 판정기 변경은 별도 승인 범위다.

## 3. 10개 워크플로우 입출력 제안

다음은 기존 내부 표의 누락을 메우는 **제안**이다. 리드가 내부 계약을 확정해야 하며 외부 support 계약은 유지한다. index/errors는 고객 요청의 하위 웹훅이 아니다.

공통 내부 envelope: `request_id`, 서버에서 확인한 `user`/`access_level`, `deadline_at`(절대 시각), `trace_id`를 전달한다. 외부에서 받은 access_level/registry/handler URL은 그대로 신뢰하지 않는다. 인증된 내부 호출에서만 신뢰 문맥을 받는다. 모든 HTTP 하위 성공은 200, 업무 오류는 200 + `{error, reason, metrics}`로 반환하고 support가 검사한다. 실제 transport 실패도 동일한 최종 fallback으로 합친다.

`metrics={llm_calls, embedding_calls, duration_ms, retries}`는 해당 하위 호출 전체의 집계로 정의한다. 부모가 자식까지 포함한 합계를 반환했다면 support가 그 자식 값을 다시 더하지 않는다. 단위는 ms, llm_calls는 이번 실행의 실제 시도 수다. timeout으로 미확정인 계측은 따로 표시한다.

| 워크플로우 / 진입 | 입력 | 정상 출력 | 오류/책임 |
| --- | --- | --- | --- |
| support / POST `ticketmoa-support` | 기존 `{request_id,user,channel,question,attempt,context}` | 기존 `{request_id,route,answer,sources,ticket,agents,security,timings,reason}` | invalid 입력만 기존 400; 차단/권한/이관은 공통 200. 신원 조회·입력 검사·중복·전체 마감·최종 합성·응답·로그의 단일 책임자 |
| agents / POST `ticketmoa-agents`, `mode=classify|verify` | classify: `{request_id,user,question,attempt,context,registry,deadline_at}`; verify: `{request_id,mode,answer,hits,record_facts,deadline_at}` | classify: `{intents,entities:{record_id,booking_id},sentiment,urgency,confidence,missing,metrics}`; verify: `{ok:boolean,issues:[],metrics}` | 기존 하나의 webhook에 mode 분기. verify에는 기록 상태·환불 계산 등 문서 밖의 허용 근거도 전달. error와 낮은 confidence를 구분 |
| refund / POST `ticketmoa-refund` | `{request_id,user,record_id?,booking_id?,context,deadline_at}` | `{route,answer,sources,pending_action,record_facts,masked,handoff_required,category,priority,metrics}` | pending 복원·본인 재조회·환불 계산·확인 상태 관리. 티켓은 직접 만들지 않고 support에 handoff 의도를 반환. 예외 상담과 확정 환불 요청을 구분 |
| index / 수동 또는 관리 POST `ticketmoa-index` | `{version,chunking?}`; 권한 있는 관리 실행 | `{version,documents,chunks,by_access,chunk_lengths:{min,median,max},issues,ready,metrics}` | 입력 문서 품질·권한별 저장·준비 검증. 고객 요청 경로에서 재색인하지 않음. 실패 시 ready=false, 이전 버전 취급 명시 |
| search / POST `ticketmoa-search` | `{request_id,query,access_level,kb_scope,top_k,deadline_at}` | `{hits:[{doc,section,score,text}],indexed,version,metrics}` | key는 서버 권한으로 검색 전 결정. staff는 all+staff 결과를 병합·중복 제거·정렬 후 top_k. 준비 실패는 error, 무관련은 빈 hits |
| tech / POST `ticketmoa-tech` | `{request_id,user,question,intents,urgency,hits,deadline_at}` | `{route,answer,sources,alert?,handoff_required,metrics}` | search는 support가 선행 호출해 hits 전달(tech에서 중복 검색하지 않음). 긴급 대체 안내를 보존. alert는 발송 의도, 직접 발송하지 않음 |
| payment / POST `ticketmoa-payment` | `{request_id,user,record_id,deadline_at}` | `{status,record,forbidden:false,masked,metrics}` 또는 `{status:403,record:null,forbidden:true,masked:0,metrics}` | 본인 조회 전용. requester는 검증 user에서 채움. 404·장애는 명시 오류. 결제 오류의 검색/이관은 support가 결합, record_id 없으면 조회하지 않음 |
| handoff / POST `ticketmoa-handoff` | `{request_id,user,summary,category,priority,alert?,deadline_at}` | `{ticket:{id,key,category,priority,duplicate}|null,duplicate,dlq,alert,reason,metrics}` | 고객 요청당 단 한 번 실행하는 부작용 소유자. LLM 없는 요약 가능. 재시도·DLQ·알림·티켓 응답 정규화. API의 지원 필드에 요약 보존 |
| errors / Error Trigger | n8n `{workflow,execution,error...}` 이벤트 | HTTP 응답 없음; `/alerts` 전송 결과 | 실제 workflow ID로 연결. 이름·노드·시각 등 허용 필드만 알림. error.message 원문을 그대로 외부로 보내지 않음. 원 요청 fallback과 분리 |
| ops / 관리 POST `ticketmoa-ops` | `{request_id,from,to,question?}`; staff 권한 확인 | `{period,total,by_route,handoff_rate,steps,dlq_size,tickets_created,answer?,metrics}` | `/logs`, `/tickets-created`, `/dlq` 읽기 전용. 비율/백분위는 Code 계산, LLM 요약은 선택. 조회 실패는 수치 0으로 위장하지 않고 error/partial 표시 |

환불 티켓을 support에서 한 번 만들자는 제안은 `docs/PROMPTS.md:106`의 refund 내부 handoff 호출과 다르다. 이 변경을 택하면 refund의 내부 POST를 제거해야 하며, 양쪽을 동시에 구현해서 중복 호출하지 않는다. 기존 nested 방식을 유지할 경우에도 refund가 만든 ticket/metrics를 반환하고 support가 다시 생성하지 않는 계약이 필수다.

## 4. 호출 순서와 결과 합성 제안

1. **관리 선행:** 팀 데이터 공급 확인 → index 실행 → all/staff 준비 확인 → 실제 errors ID 연결 → 인증 포함 통합 시험 준비. ops는 필수 통과 뒤 활성화한다.
2. **support 수신:** 시작 시각/deadline 설정 → 사용자 조회·validateRequest → 잘못된 입력 400 → detectInjection/가상 IP 규칙. 외부 context의 확인 정보는 아직 신뢰하지 않는다. 차단은 agents.llm_calls=0으로 즉시 조립한다.
3. **동일 요청 확인:** request_id 소유자/지문 대조 → 충돌이면 차단 → 동일 완료 요청이면 ticket.duplicate=true, 이번 llm_calls=0으로 재생. 진행 중 요청을 독립 신규 실행으로 취급하지 않는다. rate 계수는 합의된 적용 범위에서 처리한다.
4. **확인 상태/명확한 규칙 처리:** pending 복원, 문의번호 추출, 당일 취소·공연 임박 표현을 확인한다. 명확한 기록 조회는 payment 경로로 보낼 수 있다. 나머지는 agents.classify → JSON 의미 검증. 기술 오류/파싱 실패는 바로 이관 의도, 불확실 의도만 보완 질문(3회째는 이관)이다.
5. **업무별 자료 수집:** tech는 search→tech, refund는 refund→필요한 payment/search, 기록 조회는 payment, 결제 오류는 search(payment-error-guide)+ID 있을 때 payment를 사용한다. 암표 신고/상담원 요청은 필요한 최소 맥락만 모아 handoff 의도를 만든다. angry/high/always는 자료 수집을 무조건 생략하는 분기가 아니다.
6. **WF-12 복합 처리:** onsite/mobile 검색과 C-2002 본인 조회를 독립 분기로 시작 → tech 대체 안내와 조회 상태를 수집 → `onsite-entry-fallback` 출처를 보존 → 최종 high handoff 1회. 단순히 선 두 개와 Merge를 놓았다고 실제 병렬 지연 감소가 입증된 것은 아니다. reference의 executionOrder=v1 환경에서 HTTP 요청이 언제 시작되는지는 실행 시간표로 확인해야 한다. 병렬성이 부족해도 전체 deadline은 유지한다.
7. **검증:** 생성 답변은 agents.verify로 확인한다. `hits`에 없는 기록 상태/환불 계산을 검증할 수 있게 record_facts도 준다. 시스템 오류·권한 거절·규칙 차단·정해진 안전 안내는 LLM에 의존하지 않는다. 검증 실패 시 초안을 보내지 않고 안전 템플릿/근거 원문과 이관으로 전환한다. 마지막 마스킹/권한 출력 검사는 항상 Code로 한다.
8. **부작용:** 이관이 필요하면 handoff 한 번 호출한다. 환불 pending 확인 전에는 category=refund 실행 요청을 만들지 않는다. 일반 예외 상담 티켓과 구분한다. deadline에 따라 재시도/후속 작업을 제한한다. 실제 티켓 성공을 확인한 뒤에만 “접수 완료”와 번호를 안내한다. 티켓 실패 시 ticket=null, 접수 재처리 예정임을 명시한다.
9. **최종 합성:** 차단·권한 위반이 있는 분기의 비허용 기록/문서는 제거한다. 복합 요청에 남의 기록이 있으면 `권한 없음`을 우선하고 승인된 일반 안내만 포함한다. 나머지는 이관 > 보완 질문 > 자동 답변 순으로 합의하되 완성된 안전 안내는 보존한다. sources는 실제 사용한 근거만 중복 제거한다. agents.llm_calls와 security.masked는 각 하위의 소유 범위를 정해 중복 집계하지 않는다.
10. **응답/기록:** buildResponse로 공통 계약을 완성하고 응답 cache를 갱신한다. 로그/cache 실패가 무기한 응답을 붙잡지 않도록 짧은 timeout과 오류 출력을 둔다. Respond는 한 번만 실행한다. 로그를 응답 뒤에 보낼 경우 기록의 최선 노력 성격을 밝히고, 응답 전에 보낼 경우 전체 예산에 포함한다. 전체 p95와 하위 지연의 합은 병렬 구간 때문에 같지 않으므로 total_ms는 실측 wall-clock으로 기록한다.

## 5. 검증 범위와 다음 교차 검증 포인트

- 수행: 지정 문서·JSON·공통 함수·판정기·데이터 API·reference의 정적 대조, 각 지적의 근거 줄 확인, 산출물 파일 내용/완료 표시 확인.
- 생략: 자동 테스트·전체 회귀·n8n 실행·Credential 파손 drill·공유 서버 상태 초기화. 읽기 전용 조사/문서 작성에 대한 AGENTS.md 0단계에 따랐다. 코드나 시나리오를 수정하지 않았고 git 명령도 실행하지 않았다.
- Claude와 확인할 핵심: F01 전체 deadline, F04~06 환불 상태/slot 우선순위, F09~11 중복과 reset/repeat, F13 오류와 불확실 의도의 분리, F17 인증 실행기, F22 API 저장 필드, F27 판정 거짓 양성. 어떤 해결책을 채택하더라도 공통 기대 결과를 구현 결과에 맞춰 바꾸지 않는다.

CODEX-1-DONE
