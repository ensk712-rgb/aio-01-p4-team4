# AGENTS.md · 티켓모아 고객 기술지원 (팀 저장소 규칙)

이 파일은 코딩 에이전트(claude · codex · agy)가 작업 전에 읽는 규칙이다. claude를 쓰면 저장소 뿌리의 `CLAUDE.md`에 `@AGENTS.md` 한 줄을 둔다. 리드가 80일차에 만들고 팀이 함께 고친다.

## 1. 이 저장소가 하는 일

가상의 티켓 예매 플랫폼 티켓모아의 고객 기술 문의(모바일티켓·앱·결제 오류·입장 장애·환불 안내)를 n8n 멀티에이전트 워크플로우로 처리한다. 자동 답변, 보완 질문, 담당자 이관, 권한 없음, 차단 중 하나로 답한다.

## 2. 고정 스택 (바꾸지 않는다)

- n8n 2.42.6, OpenAI `gpt-4.1-mini`, `text-embedding-3-large`, In-Memory Vector Store
- 외부 서비스는 연습용 데이터 API(`http://localhost:8800`)만 쓴다: 예매·상담 조회 `GET /tickets/<id>?requester=`, 티켓 `POST /tickets`, 알림 `POST /alerts`, 기록 `POST /logs`, 실패 대기열 `POST /dlq`, 캐시 `/cache/<key>`
- Ollama, Supabase, 실제 Slack·Jira는 쓰지 않는다 (가산은 리드가 따로 정한다)
- 예외 (가산, 리드 허용 2026-11-06, #35): `ticketmoa-errors`·`ticketmoa-handoff`는 장애·긴급 알림을 디스코드로도 보낼 수 있다. `/alerts` 기록을 대신하지 않고, 전송이 실패해도 워크플로우는 정상 종료한다. 연락처는 가린 내용만 보낸다.

## 3. 공통 계약 (리드 허락 없이 바꾸지 않는다)

```
POST /webhook/ticketmoa-support   (Header Auth: X-Team-Key)
요청 {"request_id", "user", "channel", "question", "attempt", "context"}
응답 {"request_id", "route", "answer", "sources":[{"doc","section","score"}], "ticket",
      "agents", "security":{"blocked_by","reason","masked"}, "timings", "reason"}
route 값: "자동 답변" | "보완 질문" | "담당자 이관" | "권한 없음" | "차단"
잘못된 입력(빈 질문·없는 사용자·501자 이상): HTTP 400 {"error":"invalid request","codes":[...]}
```

하위 웹훅끼리 주고받는 모양은 `docs/IMPLEMENTATION-PLAN.md` 1단계의 하위 웹훅 표를 따른다 (설계서도 이 표에 맞춘다). 하위 웹훅은 실패해도 HTTP 200 + `{"error": "..."}`로 돌려준다.

## 4. 파일 담당 (한 사람 = 한 파일)

| 파일 | 담당 |
| --- | --- |
| `workflows/ticketmoa-support.json` | A 리드 (최두나) |
| `workflows/ticketmoa-agents.json`, `workflows/ticketmoa-refund.json` | B 오케스트레이션 (최강현) |
| `workflows/ticketmoa-index.json`, `workflows/ticketmoa-search.json`, `workflows/ticketmoa-tech.json`, `knowledge/` | C RAG (정예진) |
| `workflows/ticketmoa-payment.json`, `workflows/ticketmoa-handoff.json`, `workflows/ticketmoa-errors.json`, `data/` | D 연동·안정성 (심환석) |
| `cases/`, `requests/`, `runs/`, `docs/EXECUTION-RESULT.md` | E 시험·품질 (김인혜) |
| `workflows/ticketmoa-ops.json` (가산, Ops Assistant) | D 심환석 (필수 통과 뒤에만) |

**에이전트는 요청한 사람이 담당하는 파일만 고친다.** 다른 파일을 고쳐야 하면 고치지 말고 무엇을 왜 바꿔야 하는지 말로 알려 준다.

**임시 대행 (2026-11-07 리드 결정, 제출까지):** 팀원 부재로 최두나가 B·D·E 담당 파일을 대행한다. 최두나가 요청하면 에이전트는 이 파일도 고칠 수 있다. C 정예진 담당 파일은 대행하지 않으며, 위 규칙대로 말로 알려 준다. 고친 내용은 원래 담당자에게 알린다.

## 5. n8n 워크플로우를 만들 때

- **처음부터 JSON을 새로 쓰지 않는다.** 과정 실습의 정답 워크플로우(`~/aio-01d4-stu/Last3Mon/<일차>/reference/*.json`)를 복사해 이름·경로·노드를 고친다. 노드 `type`·`typeVersion`은 reference에 있는 것만 쓴다. 예외는 2장의 디스코드 알림에 쓰는 `n8n-nodes-base.discord` v2뿐이다.
- 워크플로우 이름과 웹훅 경로는 `ticketmoa-`로 시작한다.
- 하위 워크플로우는 Execute Workflow가 아니라 **HTTP Request로 웹훅을 부른다** (팀원마다 n8n 워크플로우 ID가 다르다). HTTP Request에는 timeout(5초)과 오류 출력을 둔다.
- 규칙으로 정할 수 있는 것(길이, 권한, 중복, 점수 기준, 금액 한도, attempt 횟수)은 Code·If·Switch로 한다. LLM은 분류·답변·검증에만 쓴다.
- Agent 출력은 JSON으로 받고, 못 읽으면 `담당자 이관`으로 간다 (fail-closed).
- 권한 판단은 질문 글이 아니라 `user`로 조회한 `access_level`로 한다. 문서 권한은 **검색 전에** 거른다 (메모리 키 `ticketmoa_kb_v1_all`, `ticketmoa_kb_v1_staff`).
- 재시도는 429·5xx·timeout만 한다. 401·403은 재시도하지 않는다.
- 티켓 생성 `key`에는 `request_id`를 넣는다 (중복 방지).
- Code 노드의 공통 처리(입력 검사, 주입 차단, 가림, 응답 조립, 재시도 판단, 환불 계산, 로그)는 **`lib/common.js`의 함수를 그대로 복사해 쓴다.** 노드 안에서 새로 짜지 않는다. 함수를 고쳐야 하면 `lib/common.js`를 고치고 `node --test lib/test/*.test.js`를 통과시킨다.
- OpenAI 노드는 모두 Credential `OpenAI (.env)`를 쓴다. 다른 이름으로 새로 만들면 `flow.py llm down`(WF-10)이 그 노드를 못 끈다.
- 환불·결제 취소를 에이전트가 직접 실행하지 않는다. 고객 확인(`context.confirm=true`) 뒤 티켓으로 넘긴다.

## 6. 절대 하지 않는 것

- API 키·토큰을 워크플로우 JSON, 문서, 코드, 커밋에 넣는 것. 키는 n8n Credential에만 있다 (이름: `OpenAI (.env)`(id `openAiCourse0001`, `Last3Mon/65/n8n/register-credentials.sh`로 등록), `ticketmoa-data-api`(X-Api-Key), `ticketmoa-team-key`(X-Team-Key), `ticketmoa-discord`(id `ticketmoaDiscord1`, Discord 웹후크 URL))
- 실제 사람의 이름·연락처를 쓰는 것. 가짜 데이터는 `010-0000-xxxx`, `@example.com`
- 응답·로그에 연락처 원문을 남기는 것 (가린 개수는 `security.masked`)
- `cases/common.json`의 기대 결과를 결과에 맞춰 고치는 것
- 시험을 통과시키려고 시나리오를 지우거나 건너뛰는 것

## 7. 바꾸기 전과 후

```powershell
git pull                                            # 바꾸기 전 (Windows 로컬)
# 내 파일만 고친다
scp workflows/<내 파일>.json aio-t4:~/aio-01-p4-team4/workflows/
ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && uv run tools/flow.py check workflows/<내 파일>.json && uv run tools/flow.py push workflows/<내 파일>.json && sleep 10 && uv run --env-file .env tools/reindex.py && sleep 5 && uv run --env-file .env tools/demo.py --warm && uv run --env-file .env tools/flow.py test cases/common.json --webhook ticketmoa-support'"
git commit -m "<무엇> · common N/14"
```

`push`는 n8n을 다시 켠다. 재시작 뒤 첫 호출에는 약 1~2초가 더 붙으므로 시험·시연 전에 `tools/demo.py --warm`으로 예열하고, 결과에 예열 여부를 적는다. `flow.py`는 저장소의 `tools/flow.py`(78일차 `flow.py`를 부르고 `.env`의 `TM_TEAM_KEY`를 `X-Team-Key`로 붙임)를 저장소 뿌리에서 쓴다. 78 원본이 다른 곳에 있으면 `FLOW_PY`로 경로를 준다. 공통 시나리오를 깨뜨렸으면 깨뜨린 사람이 고친다.

## 8. 로컬과 서버

1. 코드 탐색·수정·`node --test`는 Windows 로컬 클론에서 한다. git 작업도 로컬에서만 한다.
2. 반영은 `scp`로 서버 `aio-t4`의 `~/aio-01-p4-team4`에 한다. 서버에서 파일을 직접 고치지 않는다 (다음 반영 때 덮어써진다).
3. 서버 명령은 `ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && <명령>'"`로 실행한다. `bash -lc`가 없으면 `uv`, `claude`를 찾지 못한다. PowerShell에서 `$`는 `` `$ ``로 쓴다.
4. 서버 폴더와 n8n은 팀 전체가 하나를 쓴다. 자기 파일만 `scp`하고, 공통 폴더(`knowledge/`, `data/`, `cases/`, `lib/`)는 리드가 병합된 `main` 기준으로 올린다.
5. 서버는 Linux(Ubuntu), RAM 2.6GB를 n8n과 같이 쓴다. 오래 걸리는 작업은 `tmux`에서, 무거운 작업 전에는 `free -h`를 본다.
6. 서버의 `~/n8n/day65-n8n`과 n8n 컨테이너는 요청 없이 건드리지 않는다.
7. 서버 주소·포트·비밀번호·키·`.env` 값은 이 저장소에 적지 않는다. `.env`는 `scp`로 따로 옮긴다. 예외 (리드 결정, 2026-11-07): 평가자 확인용 공개 웹앱 URL은 산출물에 적을 수 있다. 접속 포트·웹 터미널 주소·비밀번호·키는 계속 적지 않는다.
