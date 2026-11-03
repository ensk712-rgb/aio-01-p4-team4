# 티켓모아 · 고객 기술지원 멀티에이전트 (n8n)

가상의 티켓 예매 플랫폼 티켓모아의 고객 기술 문의를 자동 분류하고, 지식 문서(RAG)와 예매 조회로 답하며, 필요한 건은 상담원에게 이관하는 n8n 워크플로우.

- 팀: 티켓모아 · 최두나(리드·통합) · 최강현(오케스트레이션) · 정예진(RAG) · 심환석(연동·안정성) · 김인혜(시험·품질)
- 기간: 2026-11-05 ~ 2026-11-09 (제출 11/09 14:50, `main` 마지막 커밋)
- 스택: n8n 2.42.6, OpenAI gpt-4.1-mini, text-embedding-3-large, In-Memory Vector Store, 연습용 데이터 API
- 입구: `POST /webhook/ticketmoa-support` (Header `X-Team-Key`)

## 디렉터리

```
aio-01-p4-team4/
├── README.md              # 이 파일 (실행 방법·웹훅 경로·시연 순서)
├── AGENTS.md              # 코딩 에이전트 규칙 (모두 먼저 읽기)
├── CLAUDE.md              # @AGENTS.md
├── docs/
│   ├── MVP.md             # MVP 범위·서버 상태·남은 위험 (먼저 읽기)
│   ├── TOPIC.md           # 주제 제안서
│   ├── PLAN.md            # 기획서 (images/architecture.png)
│   ├── IMPLEMENTATION-PLAN.md  # 구현 순서·역할·하위 웹훅 계약
│   ├── PROMPTS.md         # 역할별 바이브코딩 프롬프트
│   ├── TODO.md
│   ├── TEAM-CHARTER.md    # (80일차에 작성)
│   ├── WORKFLOW-DESIGN.md # (구현 완료 후 작성) 산출물 1
│   ├── RAG-ARCHITECTURE.md# (구현 완료 후 작성) 산출물 2
│   ├── EXECUTION-RESULT.md# (구현 완료 후 작성) 산출물 3
│   ├── daily/             # 데일리 기록 80·81·82
│   └── images/
├── workflows/             # n8n JSON, 한 사람 = 한 파일, 키 없음
│   ├── ticketmoa-support.json   최두나
│   ├── ticketmoa-agents.json    최강현
│   ├── ticketmoa-refund.json    최강현
│   ├── ticketmoa-index.json     정예진
│   ├── ticketmoa-search.json    정예진
│   ├── ticketmoa-tech.json      정예진
│   ├── ticketmoa-payment.json   심환석
│   ├── ticketmoa-handoff.json   심환석
│   ├── ticketmoa-errors.json    심환석
│   └── ticketmoa-ops.json       심환석 (가산, 필수 통과 뒤에만)
├── lib/
│   ├── common.js          # 공통 함수 원본 (Code 노드에 복사해서 씀)
│   ├── README.md          # 함수 목록·누가 어디서 쓰나
│   └── test/common.test.js
├── tools/flow.py          # 78일차 flow.py를 부르고 팀 웹훅에 X-Team-Key를 붙임
├── config/registry.json   # 업무 레지스트리 (Supervisor 프롬프트 재료)
├── config/ip-policy.json  # 가상 IP 국가·블랙리스트 (가산, TM-10~12)
├── knowledge/             # 지식 문서 8개 (staff-entry-manual만 관리자 전용)
├── data/                  # users.json 5명, records.json 5건 (가짜 데이터)
├── cases/                 # common.json(공통 14유형), team.json(팀 13개, TM-09~12는 가산)
├── requests/              # 시연·bench용 요청 파일
├── runs/                  # 시나리오 보고서 (결과서 증거)
├── webapp/                # 시연 웹앱 (상담 콘솔 + 운영), Python 표준 라이브러리만
├── deploy/                # 서버 배포 스크립트 (push → setup → doctor → run-cases)
└── drafts/n8n/            # 워크플로우 생성기(build.mjs)·격리 검증 하네스(verify/)·검토 기록
```

## 빠른 시작 (MVP)

```powershell
copy .env.example .env                                   # OPENAI_API_KEY 채우기
powershell -ExecutionPolicy Bypass -File deploy\push.ps1 -Setup
ssh -L 8080:localhost:8080 aio-t4                        # 그대로 둔 채
```

브라우저에서 http://localhost:8080 → 상담 탭에서 프리셋을 골라 보내고, 운영 탭에서 티켓·알림·DLQ·지표를 본다. 자세한 것은 `docs/MVP.md`, `deploy/README.md`, `webapp/README.md`.

워크플로우 JSON 은 `drafts/n8n/build.mjs`가 만든다. 고칠 때는 생성기를 고치고 `node drafts/n8n/build.mjs` → `drafts/n8n/verify/up.sh` → `python3 -B drafts/n8n/verify/runner.py --suite all --repeat 2` → `down.sh`.

## 처음 받은 사람

작업은 **Windows 로컬**에서 하고, 실행·검증은 **서버 `aio-t4`의 `~/aio-01-p4-team4`**에서 한다. SSH 키와 `aio-t4` 접속 설정은 팀에서 받은 `SETUP_PROMPT.md`로 먼저 끝낸다. 서버 주소·포트·비밀번호는 이 저장소 어디에도 적지 않는다.

**1. 로컬에 받기 (PowerShell)**

```powershell
git clone https://github.com/ensk712-rgb/aio-01-p4-team4.git
cd aio-01-p4-team4
git switch -c feat/<이름>-<파일>        # 예: feat/jeongyejin-search
node --test lib/test/*.test.js          # 공통 함수 테스트 (16개 통과해야 함)
ssh -o BatchMode=yes aio-t4 "whoami"   # toor가 나오면 서버 접속 준비 끝
```

**2. 서버에 반영하고 실행**

```powershell
scp -r workflows knowledge data cases config lib requests tools aio-t4:~/aio-01-p4-team4/
ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && uv run tools/flow.py push workflows/*.json'"
```

- 서버 명령은 꼭 `bash -lc`로 감싼다 (없으면 `uv`를 못 찾는다). PowerShell에서 명령 안에 `$`가 있으면 `` `$ ``로 쓴다.
- 오래 걸리는 시험은 서버 `tmux` 세션에서 돌린다. 서버 RAM이 2.6GB라 n8n과 같이 쓰므로 무거운 작업 전에 `free -h`를 본다.
- 서버에서 파일을 직접 고치지 않는다. 다음 `scp` 때 로컬 파일로 덮어써진다.
- 서버의 `~/n8n/day65-n8n`과 n8n 컨테이너는 건드리지 않는다. `.env`가 필요하면 `scp`로 따로 옮기고 git에는 올리지 않는다.

**3. 서버 폴더는 하나뿐이다**

서버 계정과 `~/aio-01-p4-team4` 폴더, n8n을 다섯 명이 같이 쓴다. 각자 아무 때나 `scp`하면 서로의 파일을 덮어쓰고 같은 웹훅 경로가 부딪친다. 그래서:

- 자기 하위 워크플로우는 **자기 파일만** 올려서 시험한다 (`scp workflows/ticketmoa-search.json aio-t4:~/aio-01-p4-team4/workflows/`).
- 공통 폴더(`knowledge/`, `data/`, `cases/`, `lib/`)는 PR이 `main`에 병합된 뒤 리드가 `main` 기준으로 올린다.
- 반영 전에 팀 채팅에 "지금 올립니다"를 한 줄 남긴다.

**4. PR**

```powershell
git add workflows/ticketmoa-search.json
git commit -m "search: 권한 필터 뒤 검색"
git push -u origin feat/<이름>-<파일>
```

GitHub에서 `main`으로 PR을 열면 리드가 검토하고 병합한다. 병합 뒤에는 `git switch main; git pull`로 최신을 받는다.

**n8n에서 손으로 할 것**: Credential 3개(`OpenAI (.env)`(id `openAiCourse0001`, `Last3Mon/65/n8n/register-credentials.sh`로 등록), `ticketmoa-data-api`(X-Api-Key), `ticketmoa-team-key`(X-Team-Key)) 만들기, 워크플로우 활성화, `ticketmoa-index` 한 번 실행. OpenAI Credential은 새로 만들지 말고 등록 스크립트가 만든 것을 고른다 (WF-10 시험이 이 Credential의 키를 잠깐 깨뜨려 확인한다). 키 값은 n8n Credentials에만 둔다.

## 시험

서버의 `~/aio-01-p4-team4`에서 실행한다.

```bash
uv run tools/flow.py push workflows/*.json
FLOW_WEBHOOK_KEY=<팀 키> uv run tools/flow.py test cases/common.json --webhook ticketmoa-support -v
FLOW_WEBHOOK_KEY=<팀 키> uv run tools/flow.py test cases/team.json -v
```

MVP 전체 배포·시험(심환석 브랜치, `deploy/`):

```bash
bash deploy/server/setup.sh                                   # import·publish·색인
python3 deploy/server/run-cases.py --suite all --repeat 1 -v  # common 17 + team 12 → runs/
bash deploy/server/doctor.sh                                  # 상태 점검
```

## 시연 순서 (발표)

조합 A: 팀 VM에서 `flow.py call ticketmoa-support requests/<파일>.json`으로 요청을 보내고 n8n 실행 화면을 함께 보여 준다. 웹 화면(가산)이 준비되면 같은 요청을 화면에서 보낸다. 웹 화면이 안 되면 그대로 `flow.py`로 시연한다.

1. WF-01 QR 문의 → 분류·검색·검증·근거  2. WF-02 보완 질문  3. WF-12 공연 10분 전 QR → 대체 입장 먼저 + 현장 알림
4. TM-02·03 환불 2단계  5. WF-04 티켓 API 장애 → DLQ·알림  6. `/logs`와 티켓 목록  7. 결과 표·실패 사례
