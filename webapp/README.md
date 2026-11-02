# 티켓모아 시연 웹앱

n8n 웹훅을 curl로 직접 부르지 않고 브라우저에서 고객 문의를 보내고 결과를 보는 앱이다. 티켓·알림·DLQ·실행 기록·지표·장애 주입도 한 화면에서 다룬다.

Python 3.12 표준 라이브러리만 쓴다. 설치할 패키지가 없고 외부 CDN도 쓰지 않아 오프라인에서 동작한다. 팀 키는 `app.py` 프로세스 안에만 있고 브라우저로 내려가지 않는다.

## 실행

### 로컬 (Windows)

```powershell
$env:TM_TEAM_KEY = "<팀 키>"
$env:TM_N8N_URL = "http://<n8n 주소>:5678"
$env:TM_DATA_API_URL = "http://<데이터 API 주소>:8800"
python webapp/app.py
```

브라우저에서 `http://localhost:8080`을 연다. macOS·Linux에서는 `python3 webapp/app.py`로 실행한다.

### 서버 (aio-t4, tmux)

서버 쪽 n8n과 데이터 API가 기본 주소(`localhost:5678`, `localhost:8800`)에 있으면 팀 키만 있으면 된다. 저장소 뿌리 `.env`에 `TM_TEAM_KEY=...`를 넣어 두면 자동으로 읽는다. `.env`는 저장소에 올리지 않고 `scp`로 따로 옮긴다.

```bash
tmux new -s ticketmoa-web
cd ~/aio-01-p4-team4 && python3 webapp/app.py
# 빠져나오기: Ctrl+B, D / 다시 붙기: tmux attach -t ticketmoa-web
```

### SSH 터널로 서버의 웹앱 보기

로컬에서 아래 명령을 실행해 둔 채 브라우저로 `http://localhost:8080`을 연다.

```bash
ssh -L 8080:localhost:8080 aio-t4
```

웹앱에는 로그인이 없다. 팀 키가 붙는 요청을 누구나 보낼 수 있으므로 `TM_HOST`를 `0.0.0.0`으로 바꾸지 말고 터널로 접속한다.

## 환경 변수

저장소 뿌리 `.env`의 `KEY=VALUE` 줄을 기본값으로 읽으며, 이미 설정된 환경 변수가 우선한다.

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `TM_HOST` | `127.0.0.1` | 웹앱이 듣는 주소 |
| `TM_PORT` | `8080` | 웹앱이 듣는 포트 |
| `TM_N8N_URL` | `http://localhost:5678` | n8n 주소 |
| `TM_TEAM_KEY` | 없음 (필수) | `X-Team-Key` 값. 없으면 시작할 때 경고하고 `/api/support`, `/api/ops`는 503으로 답한다 |
| `TM_DATA_API_URL` | `http://localhost:8800` | 데이터 API 주소 |
| `TM_USERS_FILE` | `<저장소>/data/users.json` | 사용자 목록 파일 |
| `TM_REPO` | `webapp/`의 상위 | 저장소 뿌리. `.env`, `requests/`, `cases/`를 여기서 찾는다. `.env`가 아니라 실제 환경 변수로 지정한다 |

## 웹앱 API

POST 요청은 `Content-Type: application/json`이어야 한다 (아니면 415). 다른 사이트에서 폼으로 보내는 요청을 막기 위한 조건이다. 본문은 1MB까지 받는다.

| 경로 | 동작 |
| --- | --- |
| `GET /api/users` | `users.json` 내용 그대로 |
| `GET /api/presets` | `requests/*.json`과 `cases/common.json`·`team.json`의 요청 본문을 `{group, name, request}` 목록으로 |
| `GET /api/status` | `{data_api, n8n, team_key_configured}`. 상단 연결 상태 표시에 쓴다. 키 값은 포함하지 않는다 |
| `POST /api/support` | `{TM_N8N_URL}/webhook/ticketmoa-support`로 전달 (timeout 30초) |
| `POST /api/ops` | `{TM_N8N_URL}/webhook/ticketmoa-ops`로 전달. 본문 `{from, to}` (YYYY-MM-DD) |
| `GET /api/data/<경로>` | `health`, `tickets-created`, `alerts`, `dlq`, `logs`(쿼리 그대로), `cache-stats`, `admin/fault` |
| `POST /api/data/<경로>` | `admin/fault`, `tickets-reset`, `dlq-clear`, `alerts-clear`, `cache-clear`, `logs-reset` |

- 업스트림의 상태 코드(400 포함)와 JSON 본문을 그대로 돌려준다.
- 연결 실패·timeout은 502 `{"error": ...}`로 답한다. 업스트림이 JSON이 아닌 응답을 보내면 4xx·5xx는 그 상태 코드를 유지하고 나머지는 502로 답한다. 본문은 `{"error", "upstream_status"}`다.
- 목록에 없는 데이터 경로는 404, 경로는 맞지만 메서드가 다르면 405다.
- 정적 파일은 `webapp/static/` 아래만 내준다.

## 화면

### 상담 탭

- **요청**: 사용자, 채널(web/app/phone/kiosk), 질문(500자 카운터), `request_id`, `attempt`, `booking_id`, `client_ip`, 추가 context(JSON), 시연 프리셋.
- **시연 프리셋**: 고르면 폼이 채워진다. 시나리오의 `before`(장애 주입 등)는 실행하지 않으므로 필요하면 운영 탭에서 먼저 설정한다.
- **검증**: 빈 질문, 501자, 없는 사용자도 그대로 보내 서버의 400을 보여 준다.
- **`request_id`**: 비우면 `web-<yyyymmddHHMMSS>-<4자리>`로 자동 생성한다. 같은 값을 다시 넣으면 WF-09 중복 요청을 시연할 수 있다. 프리셋은 시나리오의 고정 ID를 그대로 채우므로, 같은 프리셋을 다시 보내면 중복 요청으로 처리될 수 있다.
- **이어서 질문**: `attempt`를 1 올리고 `context.previous_request_id`, `context.previous_question`을 넣는다.
- **환불 2단계**: 응답의 `agents.pending_action`이 `refund_request`이면 `booking_id`를 자동으로 채우고 "환불 확정" 버튼을 보여 준다. 누르면 같은 사용자·같은 예매번호로 `context.pending_action="refund_request"`, `context.confirm=true`를 보낸다.
- **결과**: route 배지(자동 답변 초록, 보완 질문 노랑, 담당자 이관 파랑, 권한 없음 주황, 차단 빨강), 답변, 근거 문서 표, 티켓 카드, 에이전트, 보안, 소요 시간 막대, reason, 원문 JSON.
- **대화 이력**: 요청·응답 쌍과 시각, 소요 시간. 새로고침하면 사라진다.

### 운영 탭

상단에 기간 입력이 있고, 탭을 열거나 "전체 새로고침"을 누르면 아래 영역을 다시 읽는다.

- **지표**: 기간을 `/api/ops`로 보내 받은 결과를 표로 보여 준다.
- **실행 기록**: 최근순으로 보여 주고 route별 건수를 요약한다. `started_at`이 UTC이므로 하루 넓게 읽은 뒤 한국 날짜로 거른다.
- **티켓, 알림, DLQ**: 현재 저장된 내용.
- **장애 주입**: tickets·faq·dlq 각각 ok/slow/error/flaky와 `slow_seconds`. 시연이 끝나면 ok로 되돌린다.
- **초기화**: 티켓, DLQ, 알림, 캐시, 실행 기록. 브라우저 확인 뒤 실행한다.

페이지 상단에는 데이터 API, n8n, 팀 키 상태를 표시한다. n8n 상태는 `/healthz`만 확인하므로 팀 키가 맞는지는 알려 주지 않는다.

## 시험

```bash
python3 -m unittest webapp/test_app.py -v
```

스텁 n8n과 스텁 데이터 API를 임시 포트에 띄워 검증하므로 실제 서비스가 필요 없다.

## 한계

- 실제 n8n·데이터 API와 연결해 시험하지 않았다. 스텁과 `drafts/n8n/workflows/`의 응답 모양을 기준으로 맞췄다.
- 데이터 API 프록시는 `X-Api-Key`를 보내지 않는다. 과정 키트 77일차의 `data-api/server.py`에 키 검사가 없기 때문이다. 80일차 키트가 키를 요구하면 프록시에 헤더를 추가해야 한다.
- 워크플로우의 실행 기록은 채널을 `web|app|mobile|chat|telegram|slack|api`만 인정하므로 `phone`, `kiosk`는 기록에 `other`로 남는다.
