# Codex 3차 과제: 구현 리뷰와 mock 보정

워크플로우가 생겼다: `drafts/n8n/build*.mjs`, `lib-build.mjs`, 산출 `drafts/n8n/workflows/*.json` (노드 190개). 격리 환경이 떠 있고 현재 결과는 common 17/17, adversarial 33/33, team 11/12다.
Claude가 고친 것: compose에 게시용 `edge` 네트워크 추가, up.sh의 exec stdin 소비 수정(`</dev/null`), ready를 `/healthz/readiness`로 변경.

## 1. mock 보정
`verify/mock_openai.py`의 writer가 근거 전체를 답으로 돌려 TM-07이 `writer_too_long`이 된다. 브리프대로 "문장을 뽑아" 답하게 고친다: 질문과 개념이 겹치는 문장 위주로 최대 5문장. TM-07이면 "24시간" 문장이 나와야 한다. 판정을 약하게 만들지 않는다. mock을 바꾸면 `docker compose -p ticketmoa-verify -f verify/compose.yml restart mock-openai`로 적용한다.

## 2. 구현 리뷰 (독립, 핵심)
`drafts/n8n/workflows/*.json`의 코드 노드와 연결을 직접 읽고, 시험이 통과해도 남는 **논리 결함**을 찾는다. 코드를 고치지 말고 찾은 것을 적는다. 각 항목: 워크플로우·노드 이름, 실패 입력, 실제로 일어나는 일, 제안. 가능하면 격리 환경(포트 5699, 키는 credentials.json.example)에 실제 요청을 보내 재현하고 재현 여부를 적는다.
볼 것:
- 도달 불가 분기, 응답이 안 나가는 경로(webhook hang), 입력이 2개 온 노드의 `$json` 오해, `$('X').first()`가 루프나 미실행 노드에서 틀리는 곳, 항목이 0개가 되어 흐름이 끊기는 곳.
- Merge 앞 갈래가 항목 없이 끝나는 경우, Switch 출력 번호와 연결 번호 불일치, 재시도 카운터.
- 시간 예산: 실제 LLM 지연(분류 1~3초, 작성 2초, 검증 2초)이면 WF-01 8초를 지키는가. 시간 초과 때 사용자에게 나가는 응답이 맞는가. 부모 timeout 뒤 자식이 계속 돌아 티켓을 만드는 경우.
- 보안: 연락처 원문이 응답·로그·알림·DLQ·티켓으로 새는 길, context 신뢰, 스태프 문서 유출, 프롬프트 주입 표면(예: 복합 답변에 들어가는 record.note).
- 환불: 금액·권한·중복의 모든 조합. 다른 사용자, 다른 문의번호, 대기 만료, 재안내 뒤 확정.
- 문서 대조: docs/TOPIC.md 3절 자동 답변 금지 조건, PLAN.md 가드레일·이관 조건·핸드오프 패키지, registry.json의 escalate_if 전부가 구현됐는지. 빠진 업무 유형이 있는지.
- 각 노드 notes(한국어 설명)가 실제 동작과 다른 곳.

## 3. 산출물
`review/codex-3-review.md`. 심각도 순. 재현한 것과 코드만 읽은 것을 구분한다. 결함이 없는 영역은 "확인했고 문제 없음"으로 적는다. 마지막 줄 `CODEX-3-DONE`. git 금지. 워크플로우 파일을 고치지 않는다.
