# Codex 4차 · R01~R12 수정 재검증

2026-11-02. 기존 재현 스크립트를 새 UUID로 다시 실행하고, 반례 파일을 확장해 격리 환경에서 검증했다. 워크플로우 JSON 10개(208노드, Code 81개)의 수정 내용·연결·Switch 번호도 읽었다. 워크플로우와 생성기는 수정하지 않았으며 git 명령을 사용하지 않았다.

**결과:** 지문 충돌과 정상 환불 재안내 중복은 고쳐졌다. 확장 반례는 **47/48 통과**이며 실패는 전화번호 channel의 로그 원문 누출이다. 추가로 티켓 ID 재사용 오판과 단독 UTF-16 surrogate 입력의 500을 HTTP로 재현했다. 전체 수정 완료로 판정할 수는 없다.

## 1. 필드 수 정정

Claude의 반박이 맞다. 공통 응답은 아래 **9개**다.

`request_id, route, answer, sources, ticket, agents, security, timings, reason`

이전 Codex 2·3차 보고서의 “10개” 표현과 R12의 해당 notes 지적은 제 오류이므로 철회한다. 실제 runner의 REQUIRED 집합은 처음부터 위 9개였으므로 필수 필드 검사 동작을 약화하거나 바꾼 것은 아니다. 이번에 잘못된 주석을 정정하고 `len(REQUIRED)==9` 검증을 추가했다. 과거 보고서 원문은 감사 이력으로 보존하고 이 문서로 정정한다.

## 2. R01~R12 판정

심각도는 현재 남아 있는 문제 기준이다. “원 Code 실행”은 산출 JSON의 jsCode를 수정 없이 가져와 명시한 입력으로 로컬 실행한 것이며, HTTP 재현과 구분한다.

| 항목 | 판정 | 남은 심각도 | 재검증 결과 |
| --- | --- | --- | --- |
| R01 지문·소유자 충돌 | **부분 해결** | 높음 | 과거 32비트 충돌·question/attempt 경계 충돌 모두 400 invalid request/codes=request_id_conflict. 소유자 정확 비교·JSON 직렬화 SHA-256 확인. 다만 소유 cache가 사라지면 다른 사용자가 기존 티켓 ID를 받는 경로는 남음(§3 A). |
| R02 식별자·channel 개인정보 | **부분 해결** | 높음 | 이메일/전화 request_id는 400 invalid_request_id. 이메일 channel은 other. 전화번호 channel은 여전히 형식 정규식에 맞아 `/logs` 원문 저장(§3 B). |
| R03 재안내 후 이중 환불 티켓 | **부분 해결** | 중간 | 정상 C-2005의 안내→확정→재안내→확정은 티켓 1건·동일 ID로 해결 확인. 새 티켓 실재 확인은 ID만 비교해 재사용된 타인 티켓을 기존 환불로 오판(§3 C). |
| R04 처리 완료 건 환불 계산 | **해결 확인** | — | C-2003은 record_not_open, refund_exception 상담으로 이관. 80,000/100,000/20,000원 새 금액 안내 없음. 후속 confirm에는 유효 pending이 없어 refund 티켓을 만들지 않음. 상담 예외 티켓 자체는 허용한다. |
| R05 실패에도 접수/보관 완료 단정 | **해결 확인** | — | tickets=error·dlq=error에서 “아직 접수되지 않았습니다”, 완료/보관 문구 없음. transport 불명·DLQ 성공·양쪽 실패 문구 세 가지도 원 Code로 확인. 부모 timeout 문구는 결과 불명으로 정정됨. 늦은 POST의 본질적 불확실성은 R06/§5에 남는다. |
| R06 시간 예산 | **부분 해결** | 중간 | tech 작성 전/검증 전 부족 분기가 200 이관, 초안 미노출, LLM 0/1회로 정상 종료. 다만 비장애 이관에 2초 추가하는 정책으로 복합 지연 시 9.47초 및 응답 뒤 티켓 생성 재현(§3 D). 8초 목표 해결로 보지 않음. |
| R07 호출·재시도·재생 계측 | **부분 해결** | 중간 | 재생·충돌 로그 연결, 이번 timings/original_total_ms, llm_incomplete 로그 확인. 일반 handoff retries 전달은 구현됨. **refund 내부 handoff의 retries는 전달되지 않아 실제 재시도 경로에서도 로그 0**. SDK 내부 시도 수도 여전히 제외됨. |
| R08 staff 검색 실패 누락 | **해결 확인** | — | 원 Code에서 staff 실패→staff_search_failed, staff_indexed=false. support의 KB 오류 목록에도 포함됨. |
| R09 상태 저장 실패 | **부분 해결** | 중간 | confirm_store_failed·refund_declined:store_failed 표시와 사실 중심 안내 확인. cache 저장과 티켓 생성이 별개여서 이중 확정·철회의 원자성/내구성 보장 자체는 남음. reason 추가와 업무 상태 보장은 구분해야 함. |
| R10 한 권한 청크 0개 색인 | **해결 확인** | — | 일반 문서만 넣은 원 Code 결과 access_group_empty로 중단, store/Merge로 보내지 않음. store 오류 출력과 embedding_failed 응답도 연결됨. 부분 갱신의 원자성·문서 삭제 시 운영 절차는 §5에 남음. 공유 색인을 지우는 HTTP 재색인은 하지 않음. |
| R11 Ops 기간·조회 실패 | **부분 해결** | 중간 | 기본 KST 오늘, logs 실패 시 total/by_route=null, partial=logs, *_now 필드 확인. 그러나 저장 로그 UTC 날짜와 API의 문자열 날짜 필터가 어긋나 KST 자정~09시 집계가 빠짐(§3 E). |
| R12 요약·알림·notes | **부분 해결** | 중간 | 요약에 다음 조치/확신도 추가, title 한도 500자, 알림 성공 이력 분리 확인. “9칸” 지적은 철회. **알림 HTTP 비2xx도 성공 이력으로 저장할 수 있는 새 연결 문제**는 남음(§3 F). |

## 3. 남은 문제와 새 결함

### A. 높음 · R01 부분 해결: cache 소실 후 티켓 소유권 검증 없음 [HTTP 재현]

- **위치:** support 「중복 기록 조회」「중복 판정」「소유 기록」, handoff 「티켓 생성」「티켓 판정」. `workflows/ticketmoa-support.json:335`, `:544`; 경로는 모두 `drafts/n8n/` 기준이다.
- **입력/순서:** 김하늘이 고유 ID `codex4-7107e090ff-owner-cache`로 C-2002 상태+상담원 요청 → T-2001 생성. `/cache-clear`로 **cache 만료/소실만 모사**하고 티켓은 유지. 박서준이 같은 ID로 다른 상담 요청을 보냄.
- **실제:** 박서준에게 HTTP 200, T-2001, duplicate=true가 반환됐다. API의 실제 티켓 requester는 김하늘이다. 과거 C-2002 답변 전체가 재생된 것은 아니지만 **타인 티켓 식별자를 자기 접수처럼 안내**한다.
- **원인:** cache owner가 없으면 새 요청으로 간다. 데이터 API는 key만 보고 기존 ticket_id를 반환하며, handoff는 원 requester를 확인하지 않고 새 요청의 category/priority를 붙인다.
- **제안:** cache 소실/만료 시 `/tickets-created`에서 key의 owner도 대조하고, 소유·지문을 확인할 수 없으면 기존 티켓을 노출하지 않는다. 영구 소유권과 동시성까지 보장하려면 API 측 멱등 계약/내구 저장이 필요하지만, **이 순차 재현은 현 API의 조회로도 방어를 보강할 수 있다.** API 제약만의 문제로 넘기면 안 된다.

### B. 높음 · R02 부분 해결: 전화번호 channel은 여전히 원문 로그 [HTTP/러너 실패]

- **위치:** support 「입력 검사」(`workflows/ticketmoa-support.json:81`), 「실행 기록 조립」(:1671), 재생/400 기록의 channel 처리.
- **입력:** `channel:"010-0000-9901"`, 정상 본인 상태 조회, 고유 request_id.
- **실제:** 200 정상 응답 후 로그 channel에 전화번호 원문이 저장됐다. 새 반례 `ADV4-channel-phone`이 이 이유 하나로 실패했다. `[A-Za-z0-9_-]{1,30}`은 하이픈 전화번호에도 맞는다. 숫자만 있는 전화번호도 같은 문제가 가능하다.
- **제안:** channel은 web/app 등 승인 enum으로 정규화하거나 최소한 maskPII 검사도 적용한다. 정상·재생·400 로그 모두 같은 정책을 적용한다. request_id 제한은 이번 재현에서 정상 작동했다.

### C. 중간 · 새 결함: “확정 유효 판정”이 재사용된 ticket_id를 타인 티켓과 혼동 [HTTP 재현]

- **위치:** refund 「확정 유효 판정」(`workflows/ticketmoa-refund.json:519`), 「기존 티켓 답」. 생성기 `build-core.mjs:550`의 `list.some(t => t.ticket_id === existing.ticket.id)`.
- **입력/순서:** 깨끗한 격리 상태에서 이도윤/C-2005 안내→확정으로 T-2001 생성. **pending cache는 유지한 채 `/tickets-reset`**. 박서준의 다른 key로 티켓을 만들면 API가 T-2001을 재사용한다. 이도윤이 환불 금액 재안내 요청.
- **실제:** “이미 접수된 환불 요청, 접수 번호 T-2001”과 옛 refund key를 반환했다. 실제 T-2001은 박서준/general/다른 key다. 이도윤의 원 환불 티켓은 reset으로 없어졌다.
- **제안:** id뿐 아니라 `key == existing.ticket.key`, `requester == 현재 user`, category 등 업무 식별자를 같이 비교한다. reset과 cache의 생명주기가 다른 만큼 ID 재사용도 고려해야 한다. **현 `/tickets-created` 응답에 필요한 필드가 있어 워크플로우만으로 고칠 수 있다.**
- **검증 범위:** 의심했던 `$('기존 확정 판정').isExecuted` 선택 자체는 정상이다. quote/confirm × 기존 티켓 있음/없음 네 경우를 원 Code로 실행해 existing/quote/none 분기가 맞음을 확인했다. 이 결함의 원인은 미실행 노드 접근이나 Switch 번호가 아니라 비교 조건이다.

### D. 중간 · R06: 8초 초과와 응답 뒤 티켓 생성 [HTTP 재현, 의도된 정책의 영향]

- **입력:** 정상 QR 질문(고유 ID), mock slow_seconds=1.9, tickets=slow/8초.
- **실제:** **9.470초**, 200 이관, ticket=null, verification_timeout:timeout_or_network. DLQ에는 보관됐고, 응답 후 같은 key의 실제 티켓 **T-2002**가 만들어진 것도 관측했다.
- **해석:** 현재 브리프가 밝힌 “비장애 이관에는 최소 2초 추가” 선택과 일치한다. 이것을 숨겨진 새 회귀라고 부르지는 않지만 **8초 제약을 만족했다는 판정도 할 수 없다.** 기본 WF-11 하나를 그대로 실패시킨 것이 아니라 LLM+생성 API 복합 지연 반례다. 늦은 티켓과 DLQ가 공존하므로 재처리는 같은 key를 써야 한다.
- **별도 정상 확인:** tech deadline 이미 경과→LLM 0회, 작성 후 검증 예산 부족→LLM 1회. 둘 다 200 이관·answer 빈 문자열이며 webhook hang은 없었다. 「시간 부족 결과」의 미실행 「작성 결과 검사」 접근은 isExecuted로 안전하게 처리된다.
- **제안:** 8초 목표와 접수 보장 중 어떤 계약을 택할지 리드가 명시해야 한다. 목표를 유지한다면 추가 예산·동기 티켓 생성 대신 제한 시간 내 응답과 신뢰할 수 있는 후속 처리/결과 조회를 설계해야 한다.

### E. 중간 · 새 결함: Ops의 KST 오늘과 로그 API의 UTC 날짜 필터 불일치 [원 API 함수 실행]

- **위치:** ops 「기간 정리」(`workflows/ticketmoa-ops.json:33`)와 「실행 기록 읽기」(:48); support의 started_at=`new Date(...).toISOString()`; 과정 77 `data-api/server.py:120` query_logs.
- **실패 예:** KST `2026-11-03 00:30`의 로그 started_at은 `2026-11-02T15:30:00.000Z`. Ops는 from/to=11-03을 보낸다. API는 시각을 변환하지 않고 started_at[:10]=11-02로 비교해 제외한다.
- **재현:** 원 query_logs 함수를 그대로 읽어 이 1개 fixture로 실행하면 실제 [] / 기대 1개다. 공유 시계를 바꾸거나 실제 API에 미래 로그를 넣지는 않았다.
- **제안:** UTC 날짜를 넓게 조회한 뒤 워크플로우에서 KST 기간으로 재필터링하거나, 저장 시각/조회 날짜의 시간대 계약을 통일한다. 이는 현재 API로도 보완 가능한 코드 문제다. API의 나이브 시각 기본값과 명시적 ISO Z 로그가 섞이지 않게 해야 한다.

### F. 중간 · 새 결함: 알림 HTTP 실패가 성공 이력으로 저장될 수 있음 [연결·설정 확인]

- **위치:** handoff 「긴급 알림」(`workflows/ticketmoa-handoff.json:377`) → 「긴급 이력 저장」(:414). 장애 알림도 같은 형태다.
- **실패 조건:** POST /alerts가 401/403/429/500 등 HTTP 응답을 반환한다.
- **실제 연결:** 공통 HTTP 노드의 neverError=true 때문에 비2xx도 main 출력 0이다. 새 연결은 이 출력이면 무조건 `urgent-alerted:<id>=true`를 저장한다. 그 뒤 전송이 복구되어도 이력을 보고 알림을 생략한다. transport 오류 출력 1은 저장을 건너뛰므로 그 경우는 개선됐다.
- **제안:** readHttp의 2xx/error/stored 성공 여부를 검사하는 If 뒤에서만 이력을 저장한다. POST 응답의 성공 출력 번호와 업무 성공을 동일시하면 안 된다.
- **구분:** 현재 과정 API는 alerts 개별 HTTP fault 스위치가 없어 **HTTP 500 알림을 실제 주입하지 않았다**. 설정과 연결에서 확인한 결함이다. 워크플로우에 조건을 추가하면 고칠 수 있으므로 과정 제약으로 불가피한 문제는 아니다.

### G. 중간 · 새 결함: SHA-256 보정에서 단독 surrogate 질문이 500 [HTTP+원 함수 재현]

- **위치:** support 「중복 판정」(:335)의 sha256 → encodeURIComponent, q_hash 계산. `build-core.mjs:13` 및 `:965`.
- **입력:** 정상 user/channel/고유 request_id, JSON question 값이 escaped `"\ud800"`인 요청. 길이는 1이고 빈 질문이 아니어서 입력 검사를 통과한다.
- **실제:** **HTTP 500 `{"message":"Error in workflow"}`**. 원 SHA 함수에 같은 입력을 넣으면 `URIError: URI malformed`가 발생한다. 정상 ASCII/한글/emoji의 SHA-256은 Node crypto와 일치했다.
- **제안:** question의 Unicode 유효성을 입력 단계에서 확인해 400으로 거절하거나, 표준 UTF-8 인코딩의 replacement 정책으로 안전하게 변환한다. 해시 단계 예외가 응답 fallback을 건너뛰지 않도록 한다. 정상 문자열에 대한 SHA-256 계산 자체가 틀렸다는 지적은 아니다.

## 4. 실행한 검증과 산출물

### 재현 및 반례

- 실행 전 `pgrep`으로 다른 runner가 없음을 확인했다. 사용자가 허용한 ticketmoa-verify(5699/8899/8898)만 사용했다.
- 기존 `repro_codex3.py`, `repro_codex3_followup.py`를 각각 새 UUID로 재실행했다. 로그는 `verify/reports/codex4-repro-basic.txt`, `codex4-repro-followup.txt`; JSON은 `codex3-4bef6f9079cb.json`, `codex3-3600bd196dba.json`이다. prefix의 codex3은 기존 도구 이름이며 새 ID다.
- `verify/adversarial.json`에 **문서 근거를 먼저 명시한 6개 그룹/15단계**를 추가했다: 알려진 지문 충돌, attempt 경계, 연락처 request_id/channel, 정상 견적→확정→재안내→확정, 완료 기록 환불, 티켓·DLQ 동시 실패 안내. 기존 19개 그룹/33단계는 삭제·완화하지 않았다.
- runner에 adversarial 전용 `--id-prefix`를 추가해 의도적인 같은 ID 재사용은 유지하면서 실행별 ID를 분리했다. 기존 시나리오 파일 `cases/`는 수정하지 않았다.
- 실행 명령: `python3 -B runner.py --suite adversarial --id-prefix codex4-130754`.
- **결과: 기존 33/33, 추가 14/15, 총 47/48.** 실패는 `ADV4-channel-phone`: `logs raw contact leaked: 010-0000-9901`.
- 보고서: `verify/reports/adversarial-20261102-130825-441477.json`, 출력 `codex4-adversarial-run.txt`. 실패를 통과로 만들도록 판정을 바꾸지 않았다.

### 검증 도구의 변경

- 필드 수 주석을 9개로 정정했다. 원본 field/as_text/judge는 그대로이며 AST 동일성 검증도 통과했다.
- 임의 가짜 연락처도 지정해 sink에서 검사하는 `no_raw_contacts`, 환불 실행 요청 category 금지, 금액/완료 문구 regex 금지 검사를 추가했다.
- 반환 ticket과 API 실제 행의 requester/key도 대조하도록 엄격 검사를 보강했다. 이는 새 티켓 실재 확인이 단순 id 존재 검사로 퇴행하지 않게 하기 위함이다.
- `python3 -B -m unittest -v test_harness`: **18/18 통과**. 결과 `verify/reports/codex4-unit-tests.txt`.

### 수정 노드·추가 재현

- `recheck_nodes_codex4.mjs`: **15개 명시적 원 Code 확인 통과**, 208노드/81 Code의 문법·연결 대상·Switch extra 출력 수 확인. 근거 `verify/reports/codex4-node-evidence.json`(리뷰한 JSON 해시 포함).
- 실제 HTTP 추가 재현: `verify/repro_codex4.py` → `verify/reports/codex4-7107e090ff-targeted.json`(ID 재사용, cache 소실, Unicode 500).
- tech 예산 두 갈래: `verify/reports/codex4-0ac4137ff1-tech-budget.json`.
- 복합 지연/늦은 생성: `verify/repro_codex4_deadline.py` → `verify/reports/codex4-b129819f35-deadline.json`; 로그 `codex4-deadline-logs.json`에서 llm_incomplete=true도 확인.
- KST 경계 함수 재현: `verify/reports/codex4-kst-evidence.json`.
- common ×3 51/51, team 12/12는 브리프/Claude 결과와 최근 보고서를 확인했다. **이번에 Codex가 common/team 전체를 다시 실행한 결과라고 주장하지 않는다.** 필요한 재현·확장 adversarial 전체·도구 회귀만 실행했다.

## 5. 현 API·과정 제약과 구분해야 할 남은 위험

| 위험 | 현재 제약 | 구분/대응 |
| --- | --- | --- |
| 동시에 들어오는 확정·소유권 예약 | cache는 GET/POST/TTL이고 CAS·원자적 소비·업무 transaction이 없음. ticket key는 request_id 단위 | 현재 방식으로 원자 보장은 불가. 직렬화/영속 업무 상태/원자 API 등이 필요하다. 단, 이번 순차 cache 소실·재사용 ID 오판은 조회·비교 보강으로 개선 가능하다. |
| 티켓 생성과 confirmed 상태의 원자성 | API POST와 cache POST가 별개. 확정 저장 실패 시 티켓만 남을 수 있음 | reason 표시는 유용하지만 이중 접수 방지 완료와 같지 않다. 기존 티켓을 업무 key로 찾아 수습할 규약이 필요하다. |
| timeout 뒤 생성 취소 | 과정 API는 sleep 후 caller 연결 상태와 무관하게 생성한다. 취소/조회-by-key 계약도 제한적 | 불명 결과를 실패 확정으로 말하지 않고 같은 key로 수습. DLQ 재처리 때 새 ID 금지. 늦은 생성은 이번에 직접 관측했다. |
| 실제 환불 가능 상태 | records.status는 상담 처리 상태이며 booking/refund 상태를 구조적으로 제공하지 않음 | 접수됨 외에는 보수적 예외 상담으로 넘기는 현재 수정은 안전하다. 정확한 업무 자동화에는 데이터 계약 보완 필요. |
| 두 In-Memory store 갱신 | all/staff의 원자 교체·영속 보장 없음, 현재 키 이름 고정 | 빈 한쪽 중단은 해결됐지만 임베딩 실패 중 부분 교체와 삭제 정책은 운영 절차가 필요하다. 재시작/재색인·성공 확인을 문서화한다. |
| 실제 모델/SDK 계측 | mock은 규칙 fixture, SDK 내부 시도/비용은 현재 Agent 회수 집계와 다름 | llm_incomplete와 Agent 시도 수의 의미를 명시한다. refund retry 전달 누락은 API 제약이 아닌 코드 누락이다. |
| 결제·취소 직접 실행 금지 | 과정에서는 티켓 접수만 허용 | 유지됨. 이번 재현에서도 돈이 움직인 것은 아니며, 발견한 문제는 정보 노출·업무 접수/집계의 오류다. |

전화번호 channel, 티켓 owner/key 비교, 알림의 비2xx 성공 이력, Unicode 검증, KST 로컬 필터는 **현 스택 안에서 수정 가능한 문제**다. 이들을 API 한계로 분류하지 않는다. 시간 8초 초과는 브리프에 명시한 정책 선택이지만 목표/평가 조건과의 충돌은 남는다.

## 6. 종료 상태

원본 cases/lib/과정 키트, 생성기, 워크플로우는 수정하지 않았다. 격리 전용 API의 cache/ticket/log 등 초기화와 fault 주입은 이번 재검증에서 사용했고, 끝에는 mock=ok 및 데이터 API fault 전부 ok/slow_seconds=8로 복원했다. 공유 n8n 재배포/재시작·재색인은 하지 않았다. 늦은 생성도 기다려 관측한 뒤 fault를 복원했다. 테스트 티켓·DLQ·로그에는 codex4 prefix가 남으므로 운영 지표와 구분해야 한다.

CODEX-4-DONE
