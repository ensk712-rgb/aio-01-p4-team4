# 티켓모아 MVP · 범위와 현재 상태

2026-11-02 작성 (심환석, `hwanseok` 브랜치). 구현은 Claude(Fable 감독 + Opus 5.5 worker 2개)와 Codex 교차 검토로 했다. 상세 설계 결정은 `drafts/n8n/review/`에 있다.

## 1. MVP 범위

| 포함 | 내용 | 위치 | 상태 |
| --- | --- | --- | --- |
| 워크플로우 10개 | support·agents·refund·index·search·tech·payment·handoff·errors·ops. AGENTS §3 계약, 5경로, 400, 주입 차단, 권한 필터, 중복, 재시도·DLQ·알림, 환불 2단계, 레이트리밋·IP 정책(가산) | `workflows/` | mock LLM 격리 검증 129/129 |
| 공통 함수 | 입력 검사·주입·가림·응답 조립·재시도·환불 계산·로그·channel 정규화 | `lib/common.js` | `node --test` 18/18 |
| 웹앱 | 상담 콘솔(요청 작성·프리셋 32개·이어서 질문·환불 확정·결과 시각화·대화 이력) + 운영(지표·실행 기록·티켓·알림·DLQ·장애 주입·초기화) | `webapp/` | unittest 23/23, 서버 실연동 확인 |
| 서버 배포 | 데이터 API 컨테이너, Credential·워크플로우 import, 웹앱 tmux, 상태 점검, 시나리오 러너 | `deploy/` | 서버 `aio-t4`에 배포 완료 |
| 생성기·검증 하네스 | 워크플로우 JSON 생성기(`build.mjs`), 격리 docker 하네스(mock OpenAI), 적대 케이스 71건 | `drafts/n8n/` | 유지 (저장소 규칙상 초안 폴더) |

**뺀 것(의도적)**: 실제 Slack·Jira·Supabase·Ollama 연동(AGENTS §2), 게이트 장애 3건 집계 알림, 서버 측 attempt 카운트, 웹앱 로그인(터널 접속 전제), `docs/WORKFLOW-DESIGN.md`·`RAG-ARCHITECTURE.md`·`EXECUTION-RESULT.md`(산출물 문서는 실제 LLM 결과가 나온 뒤 각 담당이 쓴다).

## 2. 동작 흐름 (한 줄)

웹앱 → `POST /webhook/ticketmoa-support`(X-Team-Key) → 입력 검사·주입·레이트리밋·IP → 중복 확인(`/cache`, `/tickets-created`) → 규칙 빠른 길(C-번호 상태 조회는 LLM 없이) 또는 Supervisor 분류(`ticketmoa-agents`) → 권한별 검색(`ticketmoa-search`) + 조회(`ticketmoa-payment`) → 답변·검증(`ticketmoa-tech`/`ticketmoa-refund`) → 이관이면 `ticketmoa-handoff`(티켓·DLQ·알림) → 응답 조립 → `/logs` 기록. 실패는 모두 `담당자 이관`으로 닫힌다(fail-closed).

## 3. 실행 상태 (2026-11-02 기준)

**로컬(내 컴퓨터 docker `day65-n8n`)에서 실행 중.** `bash deploy/local/up.sh`로 올렸고, 실제 gpt-4.1-mini·text-embedding-3-large로 common 17/17, team 12/12 통과(`runs/all-20261102-155612.json`). 웹앱 http://localhost:8080, n8n http://localhost:5678.

실제 LLM으로 돌려 보고 고친 것: 검색 점수 기준 0.35 → 0.42(관련 질문 0.47~0.68, 무관 질문 0.38 실측), 검증 Agent에 `relevant`(근거가 질문 주제를 다루는지) 추가, "자료에 없습니다"류 답변은 규칙으로 이관. 이전에는 지식에 없는 질문(WF-03)이 결제 문서로 자동 답변됐다.

**서버 aio-t4**: 워크플로우 10개는 비활성화(unpublish)했고 웹앱·데이터 API 컨테이너는 내렸다. Credential 3개는 남아 있다(OpenAI 는 placeholder). 서버에서 다시 돌리려면 `.env`에 실제 키를 넣고 `deploy/push.sh --setup`.

## 4. 실행 (요약)

```powershell
# 1) 로컬 .env 에 OPENAI_API_KEY 를 넣는다 (.env.example 참고)
powershell -ExecutionPolicy Bypass -File deploy\push.ps1 -Setup        # 올리고 설정
ssh aio-t4 "bash -lc 'cd ~/aio-01-p4-team4 && python3 deploy/server/run-cases.py --suite all -v'"
ssh -L 8080:localhost:8080 aio-t4                                       # 웹앱 터널
```

워크플로우를 고칠 때는 JSON 을 직접 고치지 말고 `drafts/n8n/build-*.mjs`를 고친 뒤 `node drafts/n8n/build.mjs`로 재생성하고, `drafts/n8n/verify/up.sh` → `python3 -B runner.py --suite all --repeat 2` → `down.sh`로 격리 검증한다 (로컬 docker 필요).

## 5. 남은 위험·확인 필요

1. 실제 gpt-4.1-mini 답변 품질과 검색 점수 기준(0.7)은 mock 으로만 맞췄다. 실제 키로 돌린 뒤 `cases/*.json` 기대값은 그대로 두고 프롬프트·점수 기준만 조정한다.
2. 중복 요청 충돌을 400 `request_id_conflict`로 돌려주는 선택은 리드 확인이 필요하다(계약의 400 codes 에 없는 값).
3. 요청마다 `GET /tickets-created` 1회가 늘었다(티켓 주인 확인). 실서버 지연은 수십 ms 수준이었다.
4. channel 은 web·app·phone·kiosk·email 만 그대로 기록되고 나머지는 other 다.
5. 저장소 규칙(AGENTS §4 한 사람 = 한 파일)과 달리 이 MVP 는 10개 파일을 한 브랜치에서 만들었다. 팀원이 자기 파일을 가져가 검토·수정하는 것을 전제로 한다.
6. `tools/flow.py`(80일차 키트) 명령 이름이 확정되면 `deploy/`와 README 의 명령을 맞춘다.
