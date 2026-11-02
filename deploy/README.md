# 서버 배포 (`deploy/`)

로컬(Windows 또는 macOS)에서 파일을 올리고, 서버 `aio-t4`에서 `setup.sh` 한 번으로 데이터 API·Credential·워크플로우·웹앱을 올린다. 몇 번 돌려도 같은 결과다(멱등).

```
deploy/
├── push.sh / push.ps1          # 로컬 → 서버 파일 동기화 (macOS / Windows)
└── server/                     # 서버에서 실행
    ├── setup.sh                # 전체 설정 (데이터 API → .env → Credential → 워크플로우 → 색인 → 웹앱)
    ├── compose.data-api.yml    # 연습용 데이터 API 컨테이너 (n8n 네트워크, 별칭 data-api)
    ├── webapp.sh               # 웹앱 tmux 세션 start|stop|restart|status|log
    ├── doctor.sh               # 서버 상태 한눈에
    └── run-cases.py            # 시나리오 러너 (cases/common.json, team.json → runs/)
```

## 내 컴퓨터의 과정용 n8n 에 올리기 (`deploy/local/up.sh`)

서버 대신 로컬 docker 의 과정용 n8n(`day65-n8n`)에서 돌릴 때 쓴다. 과정용 데이터 API 와 같은 포트·별칭을 쓰므로 먼저 멈춘다.

```bash
docker stop day67-data-data-api-1          # 과정 실습으로 돌아갈 때: docker start day67-data-data-api-1
bash deploy/local/up.sh                     # 데이터 API → Credential → 워크플로우 → 색인 → 웹앱(http://localhost:8080)
python3 deploy/server/run-cases.py --suite all -v
bash deploy/local/up.sh --down              # 내리기
```

로컬 `.env` 의 `OPENAI_API_KEY` 가 비어 있으면 n8n 에 이미 있는 과정용 Credential(`openAiCourse0001`)로 워크플로우를 연결한다. 2026-11-02 로컬 실행 결과: common 17/17, team 12/12 (실제 gpt-4.1-mini).

## 서버에 올라가는 것

| 서버 경로 | 내용 | 출처 |
| --- | --- | --- |
| `~/aio-01-p4-team4/{workflows,lib,data,knowledge,cases,requests,config,webapp,deploy}` | 저장소 파일 | `push` |
| `~/aio-01-p4-team4/tools/data-api/server.py`, `kit-data/` | 과정 키트 77일차 데이터 API | `push` (키트 폴더에서) |
| `~/aio-01-p4-team4/tools/data-api/data/` | 실제 서비스 데이터 (`employees.json`←`data/users.json`, `tickets.json`←`data/records.json`, `docs/`←`knowledge/*.md`) | `setup.sh` 가 만든다 |
| `~/aio-01-p4-team4/.env` | 비밀값 (`OPENAI_API_KEY`, `TM_TEAM_KEY` …) | 로컬 `.env` 를 `push` 가 복사. 없으면 `setup.sh` 가 난수 팀 키와 placeholder 로 만든다 |
| n8n Credential 3개 | `OpenAI`(ticketmoaOpenAi01), `ticketmoa-data-api`(ticketmoaDataApi1), `ticketmoa-team-key`(ticketmoaTeamKey1) | `setup.sh` 가 `.env` 로 import (같은 id 로 덮어씀) |
| n8n 워크플로우 10개 | `workflows/ticketmoa-*.json` | `setup.sh` import + publish |

## 처음 한 번

1. 저장소 뿌리에 `.env` 를 만든다 (`.env.example` 복사). 최소한 `OPENAI_API_KEY` 를 넣는다. `TM_TEAM_KEY` 는 비워 두면 서버가 만든다.
2. 과정 키트가 저장소 옆에 있는지 본다: `../aio-01d4-stu/Last3Mon/77/data-api/server.py`. 다른 곳이면 `push` 에 경로를 준다.
3. 올리고 설정한다.

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File deploy\push.ps1 -Setup
# 키트가 다른 곳이면: -KitDataApi "D:\kit\Last3Mon\77\data-api"
```

```bash
# macOS / Linux
bash deploy/push.sh --setup
# 키트가 다른 곳이면: TM_KIT_DATA_API=/path/to/77/data-api bash deploy/push.sh --setup
```

`setup.sh` 끝에 `doctor.sh` 요약이 나온다. 데이터 API OK, 워크플로우 10개 활성, Credential 3개 OK 면 끝.

## 평소

```powershell
powershell -ExecutionPolicy Bypass -File deploy\push.ps1          # 파일만 올린다
ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && bash deploy/server/setup.sh'"   # 다시 import·publish
ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && bash deploy/server/doctor.sh'"
ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && python3 deploy/server/run-cases.py --suite all --repeat 1 -v'"
```

- 워크플로우 한 파일만 다시 올릴 때도 `setup.sh` 를 쓴다(10개 모두 import 하지만 id 가 같아 덮어쓴다). 색인을 건너뛰려면 `SKIP_INDEX=1`, 웹앱을 건드리지 않으려면 `SKIP_WEBAPP=1`.
- n8n 은 publish 직후 웹훅이 바로 등록되므로 재시작하지 않는다. 꼭 필요하면 `RESTART_N8N=1 bash deploy/server/setup.sh`.
- 보고서는 서버 `runs/` 에 쌓인다. 가져오기: `scp "aio-t4:~/aio-01-p4-team4/runs/*.txt" runs/`.

## 접속

서버는 22·5678 포트만 열려 있다. 웹앱(8080)은 127.0.0.1 에만 묶여 있으므로 SSH 터널로 본다.

```powershell
ssh -L 8080:localhost:8080 -L 8800:localhost:8800 aio-t4
# 브라우저: http://localhost:8080 (웹앱)  ·  n8n 은 -L 5678:localhost:5678 을 더해 http://localhost:5678 (서버 주소는 팀 채팅에서, 저장소에 적지 않는다)
```

## 확인 명령 (서버)

```bash
curl -s localhost:8800/health                                          # 데이터 API
docker exec day65-n8n-n8n-1 wget -qO- http://data-api:8800/health      # n8n 컨테이너에서
curl -s localhost:5678/healthz/readiness                               # n8n
bash deploy/server/webapp.sh status                                    # 웹앱
tmux attach -t ticketmoa-webapp                                        # 웹앱 콘솔 (Ctrl-b d 로 나옴)
```

## 문제 해결

| 증상 | 원인·조치 |
| --- | --- |
| `tools/data-api 에 키트가 없다` | 로컬에서 `push` 를 먼저. 키트 경로가 다르면 `-KitDataApi` / `TM_KIT_DATA_API` |
| 색인 응답에 `error`, 정상 문의가 모두 `담당자 이관` | `OPENAI_API_KEY` 가 placeholder. `.env` 에 실제 키를 넣고 `push` 후 `setup.sh` 다시 |
| 웹훅 403 | `X-Team-Key` 가 서버 `.env` 의 `TM_TEAM_KEY` 와 다름. 웹앱은 서버 `.env` 를 읽으므로 자동으로 맞는다 |
| 웹훅 404 `not registered` | publish 가 안 됨. `setup.sh` 다시, 그래도 안 되면 `RESTART_N8N=1` |
| 데이터 API 가 n8n 에서 안 보임 | `docker network inspect day65-n8n_default` 에 `ticketmoa-data-data-api-1` 이 있어야 한다. `docker compose -p ticketmoa-data -f deploy/server/compose.data-api.yml up -d --force-recreate` |
| 메모리 부족 | `free -h`. 데이터 API·웹앱은 각각 30MB 안팎. 무거운 것은 n8n 자체 |

## 서버에서 건드리지 않는 것

- `~/n8n/day65-n8n/` 의 파일과 n8n 컨테이너 설정. 이 스크립트는 `docker exec`(import/publish/export)와 (옵션) `docker restart` 만 쓴다.
- 서버 `~/aio-01-p4-team4/` 의 파일을 손으로 고치지 않는다. 다음 `push` 때 덮어써진다.
- `.env` 와 Credential 값은 어디에도 출력하지 않는다. `doctor.sh` 도 이름만 보여 준다.
