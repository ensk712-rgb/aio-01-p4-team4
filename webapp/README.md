# 티켓모아 상담 채팅 (시연용)

카카오톡 같은 채팅 화면에서 고객 문의를 `ticketmoa-support` 웹훅으로 보내고, 응답을 바탕으로 요청이 지나간 워크플로우 경로(입력 검사 → 보안 규칙 → 분류 → 검색·조회·환불 → 작성·검증 → 이관 → 응답)를 다시 재생한다. 예시 민원 6개는 GIF로 녹화해 발표 자료에 쓴다.

- Python 표준 라이브러리만 쓴다. 팀 키는 `app.py` 프로세스 안에만 있고 브라우저로 내려가지 않는다.
- 경로는 응답(`agents.used`, `timings`, `security`, `reason`, `ticket`)만 보고 그린다. n8n 실행 기록을 읽지 않으므로 응답에 없는 내부 분기(예: 재시도)는 보이지 않는다.

## 실행

```bash
python3 webapp/app.py                       # 로컬 n8n (.env의 TM_N8N_URL, 기본 http://localhost:5678)
TM_TARGET=vm python3 webapp/app.py          # VM n8n (.env의 TM_VM_N8N_URL)
```

브라우저에서 `http://127.0.0.1:8080`을 연다. 포트는 `TM_WEB_PORT`로 바꾼다. 오른쪽 위 예시 버튼을 누르면 질문을 자동으로 입력·전송한다.

| 주소 | 화면 |
| --- | --- |
| `/` | 고객 상담 채팅 + 흐름 그래프 |
| `/admin` | 관리자: 대화 기록, 지표, 장애 패널, 티켓·알림·DLQ·실행 기록·장애 스위치 |
| `/demo` | 발표용: 왼쪽 고객 채팅(그래프 없이) + 오른쪽 관리자. 왼쪽에서 보낸 문의가 오른쪽에 바로 뜬다 |

| 환경 변수 (.env) | 설명 |
| --- | --- |
| `TM_TEAM_KEY` | `X-Team-Key` (필수) |
| `TM_TARGET` | `local`(기본) · `vm` |
| `TM_N8N_URL` / `TM_VM_N8N_URL` | 대상별 n8n 주소 |
| `TM_WEB_HOST` / `TM_WEB_PORT` | 웹앱 주소 (기본 `127.0.0.1:8080`) |
| `TM_DATA_API_URL` / `TM_DATA_API_KEY` | local일 때 관리자 화면이 읽는 데이터 API (기본 `http://localhost:8800`) |
| `TM_ADMIN_PASSWORD` | 관리자 경로 Basic 인증. `127.0.0.1`이 아닌 주소로 열 때는 필수 |

## 관리자 화면

- **대화 기록**: `/api/chat`을 지나간 요청·응답을 `webapp/var/chats.jsonl`(git 제외)에 연락처를 가려 남긴다. 최근 500건. 화면의 "대화 기록 비우기"나 파일 삭제로 비운다.
- **장애 패널**: 고객에게는 모두 "담당자 이관"으로 보이는 건을 `reason`으로 나눈다 (`static/reasons.js`). 장애(분류·조회·LLM·티켓 실패), 품질(근거 없음·검증 불통과), 정상(설계대로 이관·거절·차단), 미분류(분류표에 없는 새 reason). 일부러 장애를 내지 않고 실제로 난 것만 보여 준다.
- **운영 데이터**: local은 데이터 API를 직접 읽고, vm은 n8n 웹훅 `ticketmoa-ops`(읽기 전용, `workflows/ticketmoa-ops.json`)를 거친다. VM 데이터 API는 밖에서 열려 있지 않기 때문이다. VM에 `ticketmoa-ops`가 없으면 탭에 그렇게 표시하고 대화 기록·장애 패널은 그대로 동작한다.

## 예시 민원 (`examples.json`)

| GIF | 민원 | 보여 주는 것 | 시나리오 |
| --- | --- | --- | --- |
| `gif/ex1-qr.gif` | QR이 안 떠요 | 분류 → 검색 → 작성 → 검증을 거친 자동 답변 | WF-01 |
| `gif/ex2-vague.gif` | 뭐가 안 되는지 모를 때 | 보완 질문 → 보충 설명 뒤 자동 답변 | WF-02 → TM-01 |
| `gif/ex3-refund.gif` | 환불 2단계 | 금액 안내 → 고객 확정 → 실행 대신 상담원 티켓 | TM-02 → TM-03 |
| `gif/ex4-urgent.gif` | 공연 10분 전 입장 문제 | 대체 입장 안내 + 긴급 티켓 + 현장 알림 | WF-12 |
| `gif/ex5-privacy.gif` | 내 문의 / 남의 문의 | 본인 건은 연락처를 가려 안내, 남의 건은 LLM 없이 거절 | WF-07 · WF-06 |
| `gif/ex6-attack.gif` | 프롬프트 주입 | 규칙으로 LLM 전에 차단 (LLM 0회) | WF-08 |

`gif/`의 파일은 2026-11-05 VM n8n(`main` e7b8eff 워크플로우)에 실제로 보낸 요청으로 녹화했다.

## GIF 다시 만들기

```bash
TM_TARGET=vm TM_WEB_PORT=8092 python3 webapp/app.py &
uv run webapp/record_gif.py --url http://127.0.0.1:8092            # 전체
uv run webapp/record_gif.py ex4-urgent --url http://127.0.0.1:8092 # 하나만
```

Playwright(Chromium)로 `?example=<id>&autoplay=1`을 열어 화면을 녹화하고 ffmpeg로 GIF(1280×720, 12fps)를 만든다. 같은 질문을 60초에 6번 넘게 보내면 TM-09 반복 요청 차단에 걸리므로 같은 예시를 연달아 녹화하지 않는다. 녹화 요청은 VM에 티켓·알림·실행 기록을 남긴다.

## 시험

```bash
python3 -m unittest discover -s webapp -p 'test_*.py'   # 설정·요청 조립
node --test webapp/test/                                # 응답 → 경로 변환 (실제 응답 모양)
```
