# Claude 1차 설계 결정 (Codex 대조용)

근거: AGENTS.md, docs/*, cases/*, lib/common.js, Last3Mon/77 data-api·flow.py, PDF 38쪽.

## 실측으로 확인한 사실
- F1. flow.py `contains`는 any-of, `not_contains`는 all-absent. `as_text`는 json.dumps 기본 구분자라 `"llm_calls": 0` 형식이 된다 (flow.py:586-597).
- F2. `agents`는 객체여야 한다. WF-08이 `"llm_calls": 0`을 agents 안에서 찾는다. PDF 12쪽의 배열 예시와 다르다 → `{"roles":[...],"llm_calls":n,...}`.
- F3. fault `tickets`는 GET /tickets/<id>와 POST /tickets에 함께 걸린다 (server.py:331-332, 411-413). slow면 POST도 8초 → WF-11(6초)에 조회 5초 + 티켓 5초는 불가능.
- F4. slow POST는 호출자가 포기해도 서버에서 티켓을 만든다 (server.py 주석). DLQ와 티켓이 공존할 수 있고 key 멱등성으로 수습된다.
- F5. POST /tickets는 title, requester, category, priority만 저장한다. summary는 사라진다.
- F6. /tickets-reset은 CREATED만 지우고 /cache는 그대로다. /cache 최대 TTL 86400, 없는 기능: 키 삭제, CAS.
- F7. 조회 API는 C-번호만 받는다. booking_id로는 찾을 수 없다 → TM-03(booking_id만 옴)에서 재조회 불가.
- F8. C-2002의 공연은 2026-11-01. WF-12의 "10분 전"을 record 날짜로 판정하면 실패한다.
- F9. n8n v1 실행 순서에서 Merge 앞 두 갈래는 동시 실행이 아니라 순차 실행이다.
- F10. 참조 노드 타입에 structured output parser, wait 노드가 없다. AGENTS 5절상 쓸 수 없다.
- F11. retryOnFail은 401·403도 재시도한다 → 수동 재시도 루프 필요 (Code의 shouldRetry).
- F12. 77 flow.py check는 credential id가 openAiCourse0001이 아니면 오류. AGENTS의 3개 Credential과 충돌한다. 80 키트에서 확인 필요.
- F13. 77 flow.py의 http()는 X-Team-Key 헤더를 보내지 않는다. Header Auth를 켜면 77 도구로 시험 불가, 80 키트 전제.
- F14. AGENTS는 localhost:8800이라 쓰지만 컨테이너 안 n8n에서는 `http://data-api:8800`이다 (모든 reference).

## 설계 결정
- D1. 시간 예산: support가 `started_ms`, `deadline_ms`(+7500), `hard_deadline_ms`(+5300)를 만들어 하위에 전달. 외부 호출 timeout = min(5000, 남은 시간). 조회 timeout 2500. 데이터 API 실패 뒤에는 hard deadline 기준. 예산이 없으면 POST /tickets 없이 DLQ로.
- D2. 규칙 빠른 길: C-번호 + 상태 묻는 말만 있으면 LLM 없이 booking_lookup (WF-06, 07, 11).
- D3. 긴급 판정은 질문 시간 표현 규칙 + (있으면) record 시각. LLM urgency는 기록만 한다. 긴급 답변은 승인 문서 기반 고정 문구 (현장 발권 보장).
- D4. 환불 2차 위조 방지: 1차에서 서버 쪽 `/cache/pending:<user>:<booking_id>` 저장. 2차는 그 값만 믿는다. context의 금액은 무시. 없으면 보완 질문, 티켓 없음. 확정 후 `confirmed`로 바꿔 다른 request_id의 이중 티켓을 막는다. TM-03은 TM-02 뒤에만 통과한다.
- D5. TM-06: 당일 표현 + refund_request면 슬롯 검사보다 먼저 이관, refund-policy를 근거로 검색.
- D6. 중복: `/cache/req:<request_id>` = {fingerprint(user+question), response}. 티켓이 있는 응답만, TTL 60초. 지문이 다르면 400 `request_id_conflict`. 재생 응답은 ticket.duplicate=true. 캐시 만료 뒤에는 POST /tickets key 멱등성이 duplicate를 준다. 60초인 이유: /tickets-reset이 캐시를 안 지워 묵은 티켓 번호를 돌려주는 문제를 최소화.
- D7. 레이트 리밋 키: `ratelimit:<user>:<질문 지문>`. 사용자 단위면 --repeat 3에서 WF-06, WF-12가 막힌다. 재생과 차단 요청은 세지 않는다. 대신 질문을 바꾸는 매크로는 못 막는다 (잔여 위험).
- D8. LLM 실패·JSON 실패는 confidence 0 처리 전에 분기 → 이관 (decideRoute로 가면 보완 질문이 되어 WF-10 실패).
- D9. Supervisor에 `clarity`(clear|vague) 추가. 등록 업무 밖이지만 분명한 질문(WF-03)은 전체 검색 → 점수 미달 → 이관. 모호(WF-02)만 보완 질문.
- D10. attempt 3이어도 LLM을 부른다. 3회째 분명해진 질문을 버리지 않는다 (PROMPTS B2와 다름, decideRoute 쪽을 따름).
- D11. WF-05: 스태프 절차 규칙이 걸리고 access_level≠staff면 RAG·LLM 없이 `권한 없음`, 금지어 없는 고정 문구. 작성 답변에는 금지어 규칙 검사 한 번 더.
- D12. 하위 웹훅도 Header Auth. 없으면 handoff·payment를 인증 없이 직접 부를 수 있다.
- D13. 복합 의도: 지원 조합은 기술 계열 + booking_lookup, payment_error + booking_lookup, refund + booking_lookup(흡수). 그 밖의 조합은 이관. route 우선순위: 이관 > 권한 없음 > 보완 질문 > 자동 답변.
- D14. 색인: 문서 머리의 access_level을 파싱하고, 없으면 색인하지 않음(fail-closed). 검색 결과 0건이면 `indexed:false` + 알림 (점수 미달과 구분).
- D15. errors 워크플로우 고정 id `ticketmoaErrors01`, 나머지가 settings.errorWorkflow로 지정. 원문·연락처 없이 이름·노드·시각만.
- D16. 응답을 보낸 뒤 /logs 기록 (응답 시간에 영향 없음). 중복 캐시는 응답 전에 저장.
- D17. 데이터 API 사용자 목록 조회 실패 시 전부 400이 되면 안 된다 → 200 + 이관 + ticket null.
- D18. Code 공통 함수는 lib/common.js에서 빌드 시 그대로 복사. Credential 이름은 AGENTS 그대로.
- D19. 초안 위치: drafts/n8n/. AGENTS 4절 때문에 다른 담당자의 workflows/ 파일에는 쓰지 않는다.

## 아직 구현하지 않는 것
- onsite-entry-fallback 5절의 "같은 공연 10분 3건 게이트 장애 알림".
- attempt는 클라이언트 값 신뢰 (서버 카운트는 WF-02 --repeat와 충돌).

## Codex 1차 검토 반영 (2026-11-02)
- F05 채택: 2차 확인 때 pending의 record_id로 본인 재조회 후 재계산. 금액이 다르면 다시 안내하고 티켓을 만들지 않는다.
- F09 채택: `/cache/req:<request_id>` 한 레코드에 소유 지문(TTL 1일)과 재생 응답(replay_until 60초)을 같이 둔다. 지문은 user+question+attempt+confirm+booking_id의 해시. 질문 원문은 저장하지 않는다. 충돌은 400 `request_id_conflict` (Codex 제안 "차단"과 다름: 계약상 형식이 틀린 요청으로 본다, 리드 확인 대상).
- F19 채택: intents 배열·등록 업무 검사, confidence 0~1 유한수, verify는 boolean true만 통과. 어기면 error → 이관.
- F21 채택(부분): show·booking_id 파싱 실패, qty·amount 이상이면 금액 계산 없이 이관. 미래 예매일은 데이터 이상으로 기록만 한다 (C-2005는 11/04 예매이고 평가 시점에는 과거가 된다).
- F22 채택: API가 summary를 버리므로 title에 가린 요약을 담는다.
- F23: 상수까지 빌드 때 복사.
- F27: 검증 러너가 ticket.id 존재, 생성 건수, DLQ·알림 건수를 따로 본다.
- 환불 티켓은 PROMPTS B4대로 refund 내부에서 handoff 호출. support는 다시 만들지 않는다.
