# Codex 3차 구현 리뷰와 mock 보정

검토일: 2026-11-02. 생성기뿐 아니라 산출된 워크플로우 JSON의 Code 노드·설정·연결·notes를 직접 읽었다. 워크플로우와 생성기는 수정하지 않았다. 변경한 실행 코드는 `verify/mock_openai.py`와 해당 단위 검사뿐이다. 검토 증거/재현 도구는 `verify/`에 보관했다. git 명령, 기존 과정 컨테이너, aio-t4, 실제 API 키에는 접근하지 않았다.

**판정:** 기존 시나리오 통과와 별개로, 다른 사용자의 답변을 받는 지문 충돌과 개인정보 로그 누출을 실제 재현했다. 환불 완료 건 재접수와 재안내 후 이중 티켓도 재현했다. 아래는 심각도 순이다. `workflows/` 경로는 `drafts/n8n/workflows/`, `verify/`도 같은 drafts/n8n 아래를 뜻한다.

## 1. 발견 사항

### R01 · 치명적 · 32비트 지문 충돌로 다른 사용자의 기록·티켓 재생 [HTTP 재현]

- **위치:** `workflows/ticketmoa-support.json:335` 「중복 판정」 → 「저장 응답 재생」(:460) → 「재생 응답」(:475).
- **실패 입력:** 같은 고유 request_id에 아래 두 요청을 차례로 전송한다. attempt=1, context 없음.
  - user=김하늘, question=`C-2002 처리 상태 알려 주세요. 상담원 연결 26189e6653ae`
  - user=박서준, question=`상담원 연결 문의 04197982c53f`
- **실제:** 두 지문은 `d286f493`이다. 첫 요청은 본인 조회 후 T-2013을 받았다. 두 번째는 HTTP 400 충돌이 아니라 **200, replayed=true, duplicate=true**로 김하늘의 C-2002 접수 상태·담당·날짜·note와 T-2013을 그대로 받았다. 일반 권한 검사는 재생 경로에서 실행되지 않는다.
- **원인:** 사용자 소유권을 독립 비교하지 않고, 전체 입력의 비암호학적 32비트 해시 하나만 비교한다. 캐시에는 owner도 저장하지 않는다. 서로 다른 질문+attempt 경계도 구분하지 않는다. 예를 들어 정민아의 `제휴 카드 포인트1`/attempt=1과 `제휴 카드 포인트`/attempt=11은 문자열 결합 단계부터 같아 T-2008을 재생했다.
- **제안:** request_id 소유 user를 독립 필드로 저장하고 정확히 비교한다. 요청 지문은 정규 JSON 배열/객체를 직렬화한 뒤 SHA-256 등으로 계산한다. confirm뿐 아니라 pending_action 등 실제 분기를 바꾸는 입력도 포함한다. 데이터 API의 티켓 key 역시 requester/요청 지문을 검증해야 캐시 장애·TTL 만료 후에도 소유권이 보장된다.
- **증거:** `verify/reports/codex3-fingerprint-collision.json`, `codex3-f6fba9fc9405.json`의 cross-user 두 응답, `codex3-b2e69eeafc77.json`의 fp-ambiguous 두 응답. 변경 없이 원 Code를 실행한 독립 증거는 `codex3-node-evidence.json`.

### R02 · 높음 · 정상 입력의 channel/request_id 연락처 원문 누출 [HTTP 재현]

- **위치:** support 「입력 검사」, 「응답 조립」(:1441), 「실행 기록 조립」(:1619). handoff 「티켓 내용 조립」은 request_id를 가리지 않고 API key로 보낸다.
- **실패 입력:** 정상 상태 조회 질문에 `channel:"010-0000-9901"` 또는 `request_id:"codex3-b2e69eeafc77-review@example.com"`을 넣는다. 전부 가짜 시험 연락처다.
- **실제:** channel 전화번호는 `/logs?source=live`에 원문 저장됐다. 이메일 request_id는 응답 request_id와 로그에 원문으로 남았다. answer의 maskPII는 이 필드를 처리하지 않는다. 이관 질문이면 같은 request_id가 ticket.key, 생성 API key, DLQ item.id, alert.request_id에도 전달될 수 있다(이 추가 sink는 코드 확인).
- **원인:** 400 기록은 channel/request_id를 가리지만 정상 기록은 단순 String/slice만 한다. 입력 검사도 channel enum이나 개인정보 없는 request_id 형식을 제한하지 않는다.
- **제안:** request_id를 프로토콜 식별자 형식으로 검증하고 연락처 포함 값은 기존 400 스키마로 거절한다. channel은 허용 enum을 사용한다. 정상/오류 로그와 부작용 전체에 동일한 가림 정책을 적용한다. ID를 응답에서만 가려 상관관계를 깨는 방식은 피한다.
- **근거/증거:** AGENTS §6(응답·로그 원문 금지), `codex3-b2e69eeafc77.json`의 channel-pii/id-pii 및 own-logs.

### R03 · 높음 · 확정 후 다시 금액을 물으면 confirmed를 pending으로 덮어써 이중 환불 티켓 [HTTP 재현]

- **위치:** refund 「환불 금액 계산」(:319) → 「대기 상태 저장」(:402), 「확인 자격 판정」(:517), 「확정 저장」(:1026).
- **실패 입력:** 같은 사용자/예매에 서로 다른 request_id로 `금액 안내 → confirm=true → 금액 다시 안내 → confirm=true`.
- **실제:** 이도윤/C-2003/T20261020-0155로 첫 확정 T-2014, 다시 안내 후 두 번째 확정 T-2015가 생겼다. 둘 다 category=refund, duplicate=false다. 바로 confirm만 반복하는 기존 반례는 통과하지만 재안내를 끼우면 막지 못한다.
- **원인:** quote 경로는 기존 pending/confirmed를 읽지 않고 같은 business key에 status=pending을 덮어쓴다. 티켓 멱등 key는 각 request_id이므로 새 confirm ID끼리는 중복 방지가 안 된다. 이 경로는 정상 C-2005에도 동일하게 적용된다(정상 건 반복은 코드 확인).
- **제안:** 확정된 업무 상태와 새 견적 상태를 분리한다. 견적 조회가 확정 이력을 지우지 못하게 하고, 동일 예매의 진행 중 환불 요청은 기존 티켓에 연결한다. request_id 멱등성 외에 business key→canonical ticket/request 매핑이 필요하다. 동시 확정은 현재 GET→POST만으로 원자성을 보장하지 못하므로 직렬화/CAS 등도 별도 필요하다.
- **증거:** `codex3-f6fba9fc9405.json`의 refunded-quote/confirm1/requote/confirm2 및 own-created-tickets. 테스트 후 해당 pending key만 이전 값으로 복원했다. 전체 cache/ticket 초기화는 하지 않았다.

### R04 · 높음 · 이미 환불 처리 완료한 기록을 새 취소 대상으로 계산·접수 [HTTP 재현]

- **위치:** refund 「환불 금액 계산」(:319), 「확인 재계산」(:713).
- **실패 입력:** user=이도윤, question=`C-2003 예매 취소 환불 얼마예요?`, 이어서 해당 booking_id confirm=true.
- **실제:** 기록 note는 이미 **100,000원 환불 처리 완료**라고 하는데, 시스템은 새 수수료 20,000원·환불 80,000원을 자동 안내하고 확정 후 category=refund 티켓을 생성했다. 실제 돈을 송금한 것은 아니지만 업무 사실과 맞지 않는 새 환불 요청이다.
- **원인:** parseBooking/calcRefund는 날짜·금액·매수만 확인한다. 취소/환불 처리 상태·기존 처리 이력은 보지 않는다. 조회의 status=ok는 HTTP/본인 조회 성공이지 환불 가능 상태가 아니다.
- **제안:** 상담 처리 상태와 예매/환불 상태를 구분하는 구조화 필드를 데이터 계약에 추가한다. 이미 취소·환불됐거나 상태가 불명확하면 추가 금액을 확정하지 않고 기존 처리 현황 또는 예외 상담으로 보낸다. note만으로 LLM이 실행 가능성을 판단하게 하지 않는다.
- **증거:** `data/records.json:32`, `codex3-f6fba9fc9405.json`, 원 Code 계산 결과 `codex3-node-evidence.json`의 already-refunded-record.

### R05 · 높음 · 환불 티켓/대기열 실패에도 “접수됐고…보관했습니다” 단정 [원 Code 실행 재현, HTTP 장애 주입 생략]

- **위치:** refund 「확인 재계산」(:713)의 ho.answer, 「이관 결과 읽기」(:975), 「이관 답」(:1063). support 「환불 결과 읽기」(:926)도 timeout이면 `환불은 진행되지 않았습니다`라고 단정한다.
- **실패 조건:** 유효 confirm 뒤 handoff transport timeout, 또는 handoff가 ticket=null/dlq=false를 반환하는 경우.
- **실제 Code 결과:** ticket=null, handoff_unavailable인데 답은 `환불 요청이 접수됐고 상담원이 처리합니다. 지금은 접수 시스템이 지연되어 요청을 대기열에 보관했습니다…`였다. 이관 결과 읽기는 handoff의 dlq/alert 성공 여부를 보존하지 않는다. 반대로 부모 timeout 뒤 자식이 티켓을 만들 수 있으므로 support의 “아무것도 확정되지 않음” 설명도 보장되지 않는다.
- **제안:** 안내 초안과 부작용 성공 문구를 분리하고, ticket/dlq의 실제 결과로 최종 문구를 정한다. timeout은 `처리 결과를 확인하지 못했습니다`로 표현하고 동일 업무의 결과를 조회·수습한다. 부모 timeout 이후에도 살아 있는 자식을 전제로 canonical key를 유지한다.
- **증거:** `codex3-node-evidence.json`의 refund-unverified-queue-claim. 공유 환경의 API fault를 켜서 이 조건을 만들지는 않았다.

### R06 · 중간 · 전역 deadline이 모든 호출/응답을 제한하지 않아 정상 QR도 이관 [HTTP 지연 재현]

- **위치:** support 「요청 시각 기록」, 「분류 호출」, 「지식 검색」, 「기술 처리 호출」(:1213), 「이관 호출」(:1301); tech 「답변 작성」/「검증 호출」.
- **입력/실측:** 고유 ID의 정상 QR 질문. mock slow는 chat뿐 아니라 embedding에도 같은 지연을 준다.
  - 호출당 1.7초: **7.561초, 자동 답변**, total_ms=7454.
  - 호출당 1.9초: **7.682초, 담당자 이관, ticket=null**, reason=`tech_unavailable:budget_exhausted`, DLQ 안내.
- **해석:** 두 요청은 모두 8초 안에 응답했다. **8초 초과를 실측했다고 주장하지 않는다.** 다만 1.9초는 지정된 작성 2초/검증 2초보다 짧은 chat 지연인데도 전체 순차 비용으로 정상 WF-01의 자동 답변 기대는 깨졌다. 이 시험의 embedding 지연 1.9초는 실제 OpenAI 임베딩 속도 가정이 아니다.
- **코드상 위험:** 분류 4초·검색 2초 등은 남은 시간과 독립이다. tech에는 deadline이 전달되지 않고, 부모 timeout 뒤에도 작성/검증은 계속된다. handoff timeout은 `남은 시간+1500`, 최소 1500ms이고 이후 cache 저장도 별도 800ms다. 따라서 deadline_ms=+7500이 전체 wall-clock 상한이라는 notes는 사실이 아니다. triage 1~3초 + writer 2초 + verifier 2초만 해도 5~7초이며 여기에 사용자/중복/rate 조회·임베딩·노드 간 HTTP·저장 시간이 더해진다.
- **제안:** 단계별 남은 예산을 전달하고 호출 시작/응답 직전에 재검사한다. 정상 답변 경로의 실제 단계 비용으로 budget을 설계한다. 사용자가 받을 최종 fallback과 자식의 늦은 완료를 분리해 기록한다.
- **증거:** `codex3-8ab5e08250a0.json`, `codex3-101dc2b7d9bd.json`. 전용 mock 상태만 잠시 바꾸고 finally에서 원 상태로 복원했다. 데이터 API fault는 변경하지 않았다.

### R07 · 중간 · LLM 호출·재시도·재생 로그의 집계가 실제와 다르다 [HTTP/기존 실행 증거+코드]

- **위치:** support 「최종 경로 결정」(:1250), 「응답 조립」(:1441), 「실행 기록 조립」(:1619), 「재생 응답」(:475); lib buildLog.
- **실제:** 1.9초 지연 응답은 agents.llm_calls=2였지만, 독점 지연 구간의 mock 통계는 triage/writer/verifier 각각 1회 증가해 **3회**였다. 부모가 tech timeout을 임의로 1회로 환산하는 동안 자식 verifier가 실행됐다. SDK retry 역시 단순히 Agent 노드 1회로 센다.
- **추가 확인:** 최신 common 51/51 보고서의 WF-04는 티켓 API 500으로 재시도하는 경로지만 저장 로그 retries=0이다. support가 handoff.retries를 전달하지 않고 buildLog의 extra.retries도 채우지 않는다. 재생 응답 노드에는 로그 연결이 없어서 --repeat의 재생은 실행 로그 자체에서 빠진다. 재생 timings도 첫 요청의 시간을 재사용한다.
- **제안:** 시도/완료/미확정 수를 구분해 실제 모델 계측과 연결한다. timeout의 미확정 호출을 0/1로 단정하지 않는다. handoff retries를 전달하고 재생/충돌도 개인정보 없는 별도 실행 로그로 기록한다. 캐시 원 실행 timing과 이번 요청 timing을 구분한다.
- **증거:** 위 두 지연 보고서의 counts(3→6, 각 role 1→2), `common-20261102-124253-586531.json`의 WF-04 로그, 재생 연결은 JSON 직접 확인. 이 common 결과는 Claude 실행을 읽은 것이며 Codex가 전체 시험을 다시 돌린 결과가 아니다.

### R08 · 중간 · 스태프 검색 실패가 성공 응답으로 사라진다 [원 Code 실행 재현]

- **위치:** search 「검색 결과 조립」(`workflows/ticketmoa-search.json:246`).
- **실패 조건:** all 검색은 성공하고 staff 검색만 failed=true. 또는 all store가 있고 staff store가 비어 있음.
- **실제 Code 결과:** staff failed=true여도 일반 hits와 indexed=true만 반환하며 error가 없다. indexed는 `a.raw.length>0`만 본다. 일반 실패는 검사하지만 `s.failed`는 검사하지 않는다.
- **제안:** 권한별 준비 상태와 실패를 각각 반환한다. 부분 검색은 partial/error로 표시하고 staff-only 질문을 일반 문서 답으로 성공시킨 것처럼 취급하지 않는다.
- **증거:** `codex3-node-evidence.json`의 staff-search-failure-ignored. 실제 embedding 장애는 양 저장소에 영향을 주는 공유 mock이어서 한쪽만 실패하는 HTTP 주입은 생략했다.

### R09 · 중간 · 견적/확정/철회 cache 저장 실패의 상태 의미가 일관되지 않다 [코드 확인]

- **위치:** refund 「금액 다시 저장」→「금액 변경 안내」, 「대기 해제」(:871)→「철회 답」(:908), 「확정 저장」(:1026)→「이관 답」.
- **실패 조건:** confirmed 티켓 생성 후 확정 저장 실패, 또는 pending 철회 저장 실패.
- **실제 경로:** 성공/오류 출력이 모두 다음 답으로 가며 저장 상태를 검사하지 않는다. 철회했다고 말했지만 기존 pending이 남을 수 있다. 티켓 성공 후 confirmed 저장 실패라면 다른 request_id의 재확인이 두 번째 티켓을 만들 수 있다. 재계산은 refund 금액만 비교하고 pending.booking_id와 재조회 record.booking_id 일치·정책 버전·예매 상태를 비교하지 않는다.
- **제안:** 저장 실패와 사용자 업무 상태를 분리하고, 확인/철회 완료를 보장하지 못하면 사실대로 안내한다. 확정 이력의 내구성·업무 중복 방지는 티켓 생성과 연결한다. 재조회 때 업무 식별자와 유효 상태도 다시 확인한다.
- **재현 범위:** 코드만 확인. 현 API에는 cache fault 개별 스위치가 없어 서버/파일을 바꾸는 주입은 하지 않았다. 정상 pending 만료는 API TTL로 처리되는 것을 확인했고, 그 조건 자체를 결함으로 보지 않는다.

### R10 · 중간 · 색인 한쪽 권한 청크가 0개인 경우 Merge/이전 store 정리 보장 없음 [코드상 위험, HTTP 미재현]

- **위치:** index 「문서 품질 검사」(:150) → 「스태프 문서?」(:201) → 두 store → 「저장 완료 모으기」(:397).
- **실패 조건:** staff 문서만 품질 검사에 탈락하거나, 관리자 문서를 없앤 새 데이터로 재색인한다. 일반 청크는 남아 있는 조건이다.
- **코드 경로:** 전체 no_chunks만 처리하고 권한별 empty는 처리하지 않는다. 한쪽 store는 clearStore/실행 자체가 안 될 수 있어 삭제한 staff 문서가 이전 메모리에 남을 수 있다. 두 입력을 기다리는 Merge가 비실행 branch에서도 정상 완료하는지 보장하는 별도 sentinel도 없다. 임베딩 store 노드의 실패는 응답 fallback 없이 Error Workflow로만 간다.
- **제안:** 두 권한의 실행/빈 store 정책을 명시하고, 빈 쪽도 안전하게 교체/비우고 완료 신호를 낸다. 버전 단위 교체로 부분 갱신/옛 문서 잔존을 막는다. store 실패도 관리 호출에 구조화된 결과를 반환한다.
- **구분:** **webhook hang을 실제로 재현한 것은 아니다.** 공유 색인을 지우거나 runtime 문서를 변조하지 않기 위해 이 조건은 코드상 위험으로 남겼다. 현재 8개 정상 문서 색인 결과를 결함으로 판정하지 않는다.

### R11 · 중간 · Ops의 “오늘”·부분 실패 설명과 실제 집계 불일치 [코드 확인]

- **위치:** ops 「운영 질문 수신」(:7), 「실행 기록 읽기」(:33), 「지표 계산」(:132).
- **실패 입력:** 기본 `{}`로 오늘 지표 질문. 또는 logs 조회만 실패하는 조건.
- **실제 경로:** from/to 기본값은 빈 문자열이라 오늘이 아닌 모든 live 로그를 센다. logs 실패 시 partial에 logs는 넣지만 total=0, by_route={}, answer=`기록된 실행이 없습니다`로 반환해 조회 실패를 빈 데이터처럼 설명한다. tickets_created/DLQ는 기간 필터 없이 현재 전체 수다.
- **제안:** 기본 기간을 KST 오늘로 정하고 각 수치의 기간/현재 snapshot 범위를 명시한다. logs 실패면 total=null과 조회 실패 안내로 구분한다.
- **근거:** PROMPTS의 Ops “오늘 이관 비율”, notes의 “읽지 못한 값은 null, 0으로 위장하지 않음”. 공유 로그에 과거 데이터를 새로 넣어 재현하지는 않았다.

### R12 · 낮음 · 핸드오프 패키지·출처·notes의 설명이 실제보다 강하다 [코드 확인]

- **위치:** support 「최종 경로 결정」(:1250), handoff 「티켓 내용 조립」(`:33`), 「긴급 알림」(:308), 「긴급 알림 필요?」(:272), search 결과 조립 및 support 응답 notes.
- **차이:** 티켓 요약은 질문 앞 120자·상태·intent·감정만 포함하며 PLAN의 분류 confidence, 마스킹된 상세 조회 정보, 실제 시도한 해결책이 충분히 담기지 않는다. API는 summary를 버리고 title 300자만 남겨 긴 요약의 다음 조치가 잘릴 수 있다. 일반 이관은 고객 응답에 쓴 문서 내용을 특정하지 않고 검색 hits 전체를 sources로 붙인다.
- **알림:** 성공 ticket.duplicate=true면 이전 긴급 알림이 성공했는지와 무관하게 다시 보내지 않는다. 최초 알림 실패 후 복구해도 유실될 수 있다. “중복 티켓이면 이미 알림을 보냈음”은 가정이다.
- **notes:** 응답 조립의 “9칸”은 실제 10칸이다. 「실행 기록 조립」의 개인정보 없음은 R02와 다르며, 「요청 시각 기록」의 모든 호출이 같은 예산을 나눠 쓴다는 설명은 R06과 다르다. 환불 이관 실패 시 확정 안 됨/보관 완료 설명은 R05와 다르다.
- **제안:** 저장 API가 지원하는 범위에서 검토 가능한 구조화 요약을 보존하고, 실제 사용 출처만 표시한다. 티켓 멱등성과 알림 전달 상태를 따로 관리한다. 위 notes를 실제 보장 범위로 좁힌다.

## 2. mock 보정과 검증

writer는 더 이상 context 전체를 붙이지 않는다. question을 함께 받아 개념·단어 중첩과 절 제목의 개념을 기준으로 원문 문장을 선택한다. “언제 풀리나” 같은 시간 질문에는 원문 시간 표현을 우선하고, 제목/Markdown 메타 줄은 제외한다. 중복 없이 최대 5문장·780자 이내를 추출한다. 답을 새로 만들거나 시나리오 ID로 정답을 하드코딩하지 않는다. 임베딩·triage·verifier·원본 판정과 기대값은 변경하지 않았다.

- 최종 mock 단위/러너 회귀: `python3 -B -m unittest -v test_harness` **15/15 통과**. 증거 `verify/reports/codex3-unit-tests.txt`.
- 지정한 Compose 프로젝트의 mock-openai 서비스만 restart하여 적용했다. n8n/data-api 재시작이나 workflow push는 하지 않았다.
- 최종 고유 요청 `codex3-492e19b39649-tm07-final`: **200, 자동 답변, fair-booking-policy 출처, 24시간 포함, 5문장, 800자 미만**. 제목 줄도 답에 없다. 증거 `codex3-492e19b39649.json`.
- **team 12개 전체 통과를 새로 주장하지 않는다.** 공유 상태를 초기화하는 전체 runner는 사용하지 않고 TM-07 관련 요청만 검증했다.

## 3. 확인했고 문제 없음 / 확인 한계

다음은 검토한 구체적 범위에서 **확인했고 문제 없음**이다. 모든 장애·동시 실행까지 검증했다는 뜻은 아니다.

- **그래프/코드 형태:** 실제 JSON 10개, 193개 노드, Code 76개를 읽어 연결 대상과 문법을 확인했다. 없는 노드 연결·main 경로에서 도달 불가인 일반 노드는 찾지 못했다. Switch의 extra 출력도 연결돼 있다. 모델/임베딩/로더는 보조 연결 노드로 별도 취급했다. 실행 시 조건부 무응답은 R10처럼 별도 구분했다.
- **support Merge:** 검색/조회 불필요 경로도 각각 `{part:...}` sentinel 한 항목을 보낸다. 「결과 합치기」가 `$input.all()`로 두 part를 찾으므로 일반적인 “둘 중 첫 $json만 읽음” 문제는 없다. search도 일반 결과를 한 항목으로 모아 staff 분기로 이어 간다.
- **재시도:** payment/handoff의 try_no 증가, 최대 최초+2회, shouldRetry의 401/403 제외, 동일 티켓 key 유지 경로를 확인했다. 설치된 n8n의 workflow-data-proxy 구현도 읽어 `$().last()`가 단순히 첫 실행의 값을 고정해 읽는다고 단정할 근거가 없음을 확인했다. 해당 반복문이 무조건 try_no=1로 되돌아간다는 결함은 찾지 못했다. 계측 누락은 R07이다.
- **권한/기본 개인정보:** 일반 고객은 검색 전에 all key만 선택한다. payment는 requester를 보내고 응답 requester도 재검사하며 maskDeep한다. 일반 고객의 직접적인 스태프 질문은 고정 거절한다. 이 정상 경로의 staff 문서 유출은 찾지 못했다. 단, R01의 응답 재생은 이 검사를 우회한다.
- **context 프롬프트:** agents 분류에는 question만 전달하고, refund에는 필요한 pending_action/confirm/booking_id만 전달한다. context.note/history 원문을 직접 모델에 넣는 연결은 없다. record.note는 마스킹 후 최종 답에 직접 합쳐지며 모델 prompt에 들어가지는 않는다. 따라서 record.note로 **LLM 지시가 실행됐다고 주장하지 않는다**. 다만 tech 검증 뒤 합쳐지는 note까지 최종 정책 검증된 답이라는 보장은 없다.
- **환불:** 선행 pending 없음·다른 사용자의 pending key·TTL 만료는 확인 티켓 없이 안내로 간다. 정상 재확정은 기존 confirmed ticket을 반환한다. 날짜/금액 형식 부족은 계산 대신 예외 이관한다. 실제 취소/결제 실행 API는 없다. 예매번호만 오는 확인은 서버 pending의 record_id로 재조회한다. 그 밖의 상태/재안내 조합 결함은 R03~05·09다.
- **문서 규칙 대조:** human_request, angry, show_day, 30만원 초과(calcRefund.needsApproval), payment_error always, scalping_report always, urgency high, fair_booking appeal_requested는 고정 코드 분기로 확인했다. 레지스트리의 현재 intent 중 빠진 handler는 찾지 못했다. handler/escalate_if 문자열을 일반적으로 해석하는 구조는 아니므로 새 레지스트리 업무를 추가하기만 하면 자동 연결된다는 설명은 성립하지 않는다. onsite-entry-fallback의 10분 3건 군집 알림은 Claude 설계에서 미구현으로 명시한 상태이며 여전히 없다.
- **Error Workflow:** 각 설정은 ticketmoaErrors01로 연결되고 errors 자신의 errorWorkflow는 없다. 오류 메시지 원문 대신 허용 필드만 알림에 넣는다. Error Trigger가 원 요청의 fallback 응답을 대신하는 연결은 없다.

## 4. 공유 환경 재현 관리와 증거

처음에는 코드 읽기/단위 검증을 먼저 수행하며 1~2분 이상 기다렸다. runner 프로세스 종료와 정상 fault 상태를 확인한 뒤 mock을 재시작했다. 이후 Claude가 common 반복 시험을 다시 시작한 구간과 겹친 초기 TM-07/no_evidence 결과는 **보정 실패의 증거로 사용하지 않았다**. 다시 runner 부재/정상 상태를 확인한 구간에서 후속 재현과 지연 시험을 했다.

모든 요청 ID는 `codex3-<uuid>-...`다. 충돌 검사만 의도적으로 같은 ID를 두 번 썼다. `/tickets-reset`, `/cache-clear`, `/logs-reset`, 재색인과 **데이터 API fault 스위치는 호출하지 않았다**. 지연은 전용 mock state만 사용했고 finally로 복원했다. 환불 재현의 특정 pending key는 기존 값을 읽어 보관한 후 복원했다. 고유 ID의 시험 티켓·실행 로그·DLQ는 증거로 남아 있으므로 이후 “전체 이관율/오늘 티켓 수”에는 이 재현 트래픽이 포함된다. 운영 지표에서 codex3 prefix를 구분해야 한다.

`verify/reports/codex3-node-evidence.json`에는 리뷰 시 읽은 JSON 해시, 그래프 검사 및 원 Code 실행 입력/결과가 있다. `verify/repro_codex3*.py`와 `review_nodes_codex3.mjs`는 원인 재현용이며 전체 runner처럼 공유 상태를 초기화하지 않는다. HTTP 재현과 Code 단독 실행을 위에서 분리했다. mock 지연 회복 후 최종 state는 정상인지 다시 확인했다.

CODEX-3-DONE
