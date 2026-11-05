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

| 환경 변수 (.env) | 설명 |
| --- | --- |
| `TM_TEAM_KEY` | `X-Team-Key` (필수) |
| `TM_TARGET` | `local`(기본) · `vm` |
| `TM_N8N_URL` / `TM_VM_N8N_URL` | 대상별 n8n 주소 |
| `TM_WEB_HOST` / `TM_WEB_PORT` | 웹앱 주소 (기본 `127.0.0.1:8080`) |

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
