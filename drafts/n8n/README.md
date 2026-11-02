# 티켓모아 전체 워크플로우 초안

워크플로우 10개의 생성기·격리 시험·검토 기록이다. 생성 결과는 저장소 뿌리의 `workflows/`에 쓴다.

- `../../workflows/*.json`: n8n에 넣는 워크플로우 10개. `node drafts/n8n/build.mjs`로 생성.
- `build*.mjs`, `lib-build.mjs`: 생성기. Code 공통 함수는 `lib/common.js`에서 원문을 복사한다.
- `ticketmoa-workflows.html`: 설명 화면. `node render/render.mjs`로 생성.
- `verify/`: 격리 시험 (포트 5699·8899·8898, mock LLM). `./up.sh` → `python3 -B runner.py --suite all --repeat 2` → `./down.sh`.
- `review/`: Claude·Codex 교차 검토 기록.

Credential id는 임시값이다: `ticketmoaOpenAi01`, `ticketmoaDataApi1`, `ticketmoaTeamKey1`.
