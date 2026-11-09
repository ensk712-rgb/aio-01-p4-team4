# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""78일차 flow.py를 그대로 부르되, 팀 웹훅 호출에 X-Team-Key 머리글을 붙인다.

78일차 flow.py는 Header Auth 키를 보내지 않아서, 팀 웹훅에 Header Auth를 걸면 call·test·bench가
모두 403이 된다. 팀 키는 환경 변수 TM_TEAM_KEY로 준다 (.env.example과 같은 이름).
옛 이름 FLOW_WEBHOOK_KEY도 당분간 받는다.

  uv run --env-file .env tools/flow.py test cases/common.json --webhook ticketmoa-support
  FLOW_PY=<다른 flow.py 경로>  (기본: ~/aio-01d4-stu/Last3Mon/78/tools/flow.py)

78일차 check는 OpenAI(openAiCourse0001) 말고 다른 Credential을 막는다. 팀 키 Credential은
tools/register-team-key.sh로 고정 id ticketmoaTeamKey1에 넣고, 여기서 그 id를 허용한다.

키 값은 저장소·문서에 쓰지 않는다. 셸에서만 넣는다.
"""
import importlib.util
import os
import sys
import urllib.request
from pathlib import Path

FLOW_PY = Path(os.environ.get("FLOW_PY", "~/aio-01d4-stu/Last3Mon/78/tools/flow.py")).expanduser()
KEY = os.environ.get("TM_TEAM_KEY") or os.environ.get("FLOW_WEBHOOK_KEY", "")

if not FLOW_PY.exists():
    sys.exit(f"flow.py not found: {FLOW_PY} (set FLOW_PY)")

_Request = urllib.request.Request


class _TeamKeyRequest(_Request):
    def __init__(self, url, *args, **kwargs):
        super().__init__(url, *args, **kwargs)
        if KEY and "/webhook/" in self.full_url:
            self.add_header("X-Team-Key", KEY)


urllib.request.Request = _TeamKeyRequest

spec = importlib.util.spec_from_file_location("course_flow", FLOW_PY)
flow = importlib.util.module_from_spec(spec)
sys.modules["course_flow"] = flow
spec.loader.exec_module(flow)
# 팀 웹훅 Header Auth Credential(tools/register-team-key.sh가 만드는 고정 id)을 check·doctor가 받게 한다.
flow.COURSE_CREDENTIALS["ticketmoaTeamKey1"] = "ticketmoa-team-key"
# 데이터 API 호출의 X-Api-Key Credential. tools/register-team-key.sh가 같은 id로 등록한다.
flow.COURSE_CREDENTIALS["ticketmoaDataApi1"] = "ticketmoa-data-api"
# 장애·긴급 알림의 Discord Webhook Credential (errors·handoff). 웹후크 URL은 이 Credential에만 있다.
flow.COURSE_CREDENTIALS["ticketmoaDiscord1"] = "ticketmoa-discord"
# 수업 원본은 유지하고 팀 시험에서 복구 실패가 후속 시험으로 이어지지 않게 한다.
from flow_hooks import HookFailure, install_strict_hooks

install_strict_hooks(flow)
try:
    sys.exit(flow.main())
except HookFailure as error:
    print(f"{flow.BAD} {error}", file=sys.stderr)
    sys.exit(2)
