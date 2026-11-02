# Codex 1차 과제: 티켓모아 전체 n8n 설계의 논리 결함 독립 검토

Claude(Opus)와 함께 팀4 프로젝트 전체를 n8n 워크플로우로 작성한다. 결론이 서로 물들지 않도록, 이 단계에서는 Codex가 독립적으로 결함을 찾는다.

## 읽을 것
- AGENTS.md, docs/PLAN.md, docs/IMPLEMENTATION-PLAN.md, docs/TOPIC.md, docs/PROMPTS.md
- config/registry.json, config/ip-policy.json, data/*.json, knowledge/*.md, lib/common.js, cases/common.json, cases/team.json, cases/README.md
- 과정 키트: ../aio-01d4-stu/Last3Mon/73/tools/flow.py (판정 방식), ../aio-01d4-stu/Last3Mon/76/data-api/server.py (또는 77의 것, 실제 API 동작), ../aio-01d4-stu/Last3Mon/{71,72,73,76,77}/reference/*.json

## 산출물
`drafts/n8n/review/codex-1-design-findings.md` 파일 하나만 쓴다. 다른 파일은 고치지 않는다. git 명령도 쓰지 않는다.

## 쓸 내용 (한국어)
1. 문서·시나리오·공통 함수·데이터 API가 서로 충돌하거나, 그대로 구현하면 시나리오가 실패하는 지점. 각 항목마다 근거 파일:줄, 실패하는 시나리오 ID, 제안하는 해결책.
   특히 볼 것: WF-11 시간 예산(LLM + 조회 + 티켓), WF-12 긴급 판정과 record 날짜, TM-03 record_id 없이 booking_id만 오는 경우와 context.confirm 위조, TM-06 slot 없는 당일 취소, 레이트 리밋이 공통 시나리오를 막을 가능성, 같은 request_id 재사용(다른 사용자·다른 질문), --repeat 3, /tickets-reset과 /cache의 관계, WF-05 답변 금지어, WF-10 LLM 멈춤 구현 방식, llm_calls 집계, In-Memory 색인 미실행 상태, Error Workflow의 워크플로우 ID 문제.
2. 위에 없어도 네가 찾은 추가 논리 결함.
3. 워크플로우 10개(support, agents, refund, index, search, tech, payment, handoff, errors, ops)의 하위 웹훅 입출력 표와 호출 순서 제안.

사실과 추정을 구분하고, 코드로 확인한 것은 확인했다고 쓴다. 끝나면 마지막 줄에 `CODEX-1-DONE` 을 적고 멈춘다.
