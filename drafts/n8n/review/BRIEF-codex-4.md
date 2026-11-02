# Codex 4차 과제: R01~R12 수정 재검증 (마지막 검토)

Claude가 `review/codex-3-review.md`의 지적을 반영해 워크플로우를 다시 빌드했고 격리 환경에 올렸다 (support, refund, handoff, search, tech, index, ops 변경). 현재 common ×3 전부 통과, team 12/12, adversarial 33/33.

반영 내용 요약:
- R01: 소유자 이름 정확 비교 + JSON 직렬화 SHA-256 지문(pending_action 포함). 충돌은 400 `request_id_conflict`.
- R02: request_id 형식 제한(영문·숫자·._:-, 80자, 연락처 금지) → 400 `invalid_request_id`. channel은 형식이 다르면 `other`.
- R03: 새 안내 저장 전에 기존 confirmed를 읽고, /tickets-created로 티켓 실재를 확인한 뒤 기존 티켓으로 답한다.
- R04: 기록 status가 `접수됨`이 아니면 금액 계산 없이 이관. 2차에도 booking_id·status 재확인.
- R05: 티켓/대기열/호출 실패별 문구 분리. "접수됐다"를 티켓 있을 때만 말한다.
- R06: tech가 deadline을 받아 LLM 시작 전·검증 전에 시간을 본다. 시간 부족이면 초안을 버리고 이관. 비장애 이관은 티켓에 최소 2초 보장(8초 초과 가능, 의도된 선택).
- R07: llm_incomplete 표시, handoff retries를 로그로 전달, 재생·충돌도 기록, 재생 timings는 이번 실행 값 + original_total_ms.
- R08: staff_search_failed, staff_indexed. R09: 저장 실패를 reason에 표시, 답 문구는 사실만. R10: all·staff 한쪽이 0개면 색인 중단. R11: 기간 기본값 KST 오늘, logs 실패 시 null, *_now 표기. R12: 요약 순서·길이, 긴급 알림 성공 이력 분리.
- 동의하지 않은 것: R12의 "9칸은 실제 10칸". 계약 칸은 request_id, route, answer, sources, ticket, agents, security, timings, reason으로 9개다. 근거를 보고 틀렸으면 반박해 달라.

## 할 일
1. `repro_codex3*.py`의 재현을 고유 ID로 다시 실행해 R01~R05가 더 재현되지 않는지 확인한다.
2. `adversarial.json`에 반례를 추가한다 (문서 근거 먼저): 지문 충돌 입력(R01), attempt 경계 입력, 연락처 request_id·channel, 금액 안내→확정→재안내→확정 시 티켓 1건, 처리 완료 기록(C-2003) 환불 시 금액 없음. 러너로 돌려 결과를 낸다. 다른 시험과 겹치지 않게, 시작 전에 Claude 시험이 돌지 않는지 확인한다.
3. 바뀐 부분을 다시 읽고 **새로 생긴 결함**이 있으면 찾는다. 특히 `확정 유효 판정`의 `$('기존 확정 판정').isExecuted` 분기, 새 Switch 번호, tech의 `시간 부족 결과`, handoff의 긴급 이력 노드, notes와 실제의 차이.
4. 남은 위험 중 현 데이터 API·과정 제약으로 못 고치는 것을 구분해 적는다.

## 산출물
`review/codex-4-recheck.md`. 항목별 "해결 확인 / 부분 해결 / 미해결 / 새 결함", 재현 여부, 심각도. 마지막 줄 `CODEX-4-DONE`. 워크플로우와 생성기는 고치지 않는다. git 금지.
