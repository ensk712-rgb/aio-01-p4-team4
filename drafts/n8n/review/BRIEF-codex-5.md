# Codex 5차 과제: §3 A~G 수정 최종 확인 (짧게)

`review/codex-4-recheck.md`의 지적을 반영해 다시 올렸다. 현재 common×3 51/51, team×3 36/36, adversarial 48/48.

반영:
- A: handoff에서 duplicate면 /tickets-created로 key·ticket_id·requester 확인. 다르거나 확인 불가면 ticket:null, reason request_id_conflict, DLQ·알림 없음. support가 "새 요청 번호로" 안내.
- B: channel은 `^[A-Za-z][A-Za-z0-9_-]{0,29}$`만, 그 밖에는 other (네 곳).
- C: 확정 유효 판정이 id·key·requester 비교.
- D: 비장애 이관의 티켓 보장을 2초 → 0.8초로 줄였다. 8초 초과 가능성은 LLM이 예산을 다 쓰고 티켓 API까지 느린 경우로 남기고 문서화한다 (Claude의 결정).
- E: ops가 하루 넓게 읽고 한국 날짜로 재필터.
- F: 긴급·장애 알림 2xx일 때만 이력 저장.
- G: 짝 안 맞는 surrogate 질문은 400 invalid_encoding, refund는 booking_id 형식 검사.
- R07: refund의 retries를 support까지 전달.

## 할 일
1. A, B, C, F, G를 고유 ID로 HTTP 재현해 확인한다. E는 원 Code로 확인한다.
2. 이번 수정분에서 새 결함을 찾는다 (예: `중복 주인 판정`이 정상 재전송을 남의 티켓으로 오판하는 경우, /tickets-created 실패 시 정상 사용자의 경험, 빠진 Switch·If 연결).
3. adversarial 전체를 한 번 더 돌린다.

## 산출물
`review/codex-5-final.md`: 항목별 판정, 새 결함(있으면 재현 방법), 그리고 "이 워크플로우 초안에 대해 남은 위험" 목록. 마지막 줄 `CODEX-5-DONE`. 워크플로우와 생성기는 고치지 않는다. git 금지. 끝에 fault와 mock을 정상으로 돌려놓는다.
