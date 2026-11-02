#!/usr/bin/env bash
# 서버(aio-t4)에서 실행. 멱등: 몇 번 돌려도 같은 결과.
#   cd ~/aio-01-p4-team4 && bash deploy/server/setup.sh
# 환경변수: WORKFLOW_DIR(기본 workflows), SKIP_INDEX=1(색인 생략), SKIP_WEBAPP=1
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
ROOT="$(pwd)"
N8N=day65-n8n-n8n-1
WORKFLOW_DIR="${WORKFLOW_DIR:-workflows}"
ORDER=(errors index search agents tech payment handoff refund ops support)

say() { printf '\n== %s\n' "$*"; }
warn() { printf '\n!! %s\n' "$*" >&2; }

# ---------- a. 데이터 API 데이터 준비 ----------
say "데이터 API 데이터 준비 (tools/data-api/data)"
[[ -f tools/data-api/server.py && -d tools/data-api/kit-data ]] || { warn "tools/data-api 에 키트가 없다. 로컬에서 deploy/push.sh 를 먼저 실행"; exit 1; }
rm -rf tools/data-api/data && mkdir -p tools/data-api/data/docs
cp -R tools/data-api/kit-data/. tools/data-api/data/
cp data/users.json tools/data-api/data/employees.json
cp data/records.json tools/data-api/data/tickets.json
rm -rf tools/data-api/data/docs && mkdir -p tools/data-api/data/docs
cp knowledge/*.md tools/data-api/data/docs/
echo "  docs $(ls tools/data-api/data/docs | wc -l)개, users $(python3 -c 'import json;print(len(json.load(open("data/users.json"))))')명, records $(python3 -c 'import json;print(len(json.load(open("data/records.json"))))')건"

# ---------- b. 데이터 API 컨테이너 ----------
say "데이터 API 컨테이너 (ticketmoa-data)"
docker compose -p ticketmoa-data -f deploy/server/compose.data-api.yml up -d --force-recreate
for i in $(seq 1 30); do curl -sf -m 2 localhost:8800/health >/dev/null && break; sleep 1; done
echo "  호스트  : $(curl -s -m 2 localhost:8800/health)"
echo "  n8n에서 : $(docker exec "$N8N" wget -qO- -T 3 http://data-api:8800/health 2>&1 || echo FAIL)"

# ---------- c. .env ----------
say ".env"
touch .env; chmod 600 .env
getenv() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
if [[ -z "$(getenv TM_TEAM_KEY)" ]]; then
  echo "TM_TEAM_KEY=$(python3 -c 'import secrets;print("tm-"+secrets.token_hex(16))')" >> .env
  echo "  TM_TEAM_KEY 를 난수로 만들었다"
fi
if [[ -z "$(getenv OPENAI_API_KEY)" ]]; then
  echo "OPENAI_API_KEY=sk-placeholder" >> .env
  warn "OPENAI_API_KEY 가 없어 placeholder 를 넣었다. 실제 키를 .env 에 넣고 setup.sh 를 다시 돌리면 같은 Credential 이 덮어써진다."
fi
[[ -z "$(getenv TM_DATA_API_KEY)" ]] && echo "TM_DATA_API_KEY=ticketmoa-data" >> .env
for k in TM_N8N_URL=http://localhost:5678 TM_DATA_API_URL=http://localhost:8800 TM_HOST=127.0.0.1 TM_PORT=8080; do
  [[ -z "$(getenv "${k%%=*}")" ]] && echo "$k" >> .env
done
set -a; . ./.env; set +a

# ---------- d. Credential 3개 (고정 id) ----------
say "n8n Credential import (OpenAI, ticketmoa-data-api, ticketmoa-team-key)"
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
python3 - "$TMP" <<'PY'
import json, os, sys
creds = [
  {"id": "ticketmoaOpenAi01", "name": "OpenAI", "type": "openAiApi", "data": {"apiKey": os.environ["OPENAI_API_KEY"], "url": "https://api.openai.com/v1"}},
  {"id": "ticketmoaDataApi1", "name": "ticketmoa-data-api", "type": "httpHeaderAuth", "data": {"name": "X-Api-Key", "value": os.environ.get("TM_DATA_API_KEY", "ticketmoa-data")}},
  {"id": "ticketmoaTeamKey1", "name": "ticketmoa-team-key", "type": "httpHeaderAuth", "data": {"name": "X-Team-Key", "value": os.environ["TM_TEAM_KEY"]}},
]
open(sys.argv[1], "w").write(json.dumps(creds))
PY
docker cp "$TMP" "$N8N:/tmp/ticketmoa-creds.json"
docker exec -u root "$N8N" chown node:node /tmp/ticketmoa-creds.json 2>/dev/null || true   # docker cp 가 root 소유로 넣는 환경이 있다
docker exec "$N8N" n8n import:credentials --input=/tmp/ticketmoa-creds.json | tail -1
docker exec -u root "$N8N" rm -f /tmp/ticketmoa-creds.json
rm -f "$TMP"

# ---------- e. 워크플로우 import + publish ----------
say "워크플로우 import·publish ($WORKFLOW_DIR)"
for n in "${ORDER[@]}"; do [[ -f "$WORKFLOW_DIR/ticketmoa-$n.json" ]] || { warn "$WORKFLOW_DIR/ticketmoa-$n.json 없음"; exit 1; }; done
docker exec "$N8N" rm -rf /tmp/ticketmoa-wf && docker exec "$N8N" mkdir -p /tmp/ticketmoa-wf
for n in "${ORDER[@]}"; do docker cp "$WORKFLOW_DIR/ticketmoa-$n.json" "$N8N:/tmp/ticketmoa-wf/"; done
docker exec -u root "$N8N" chown -R node:node /tmp/ticketmoa-wf 2>/dev/null || true
for n in "${ORDER[@]}"; do
  id=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['id'])" "$WORKFLOW_DIR/ticketmoa-$n.json")
  docker exec "$N8N" n8n import:workflow --input="/tmp/ticketmoa-wf/ticketmoa-$n.json" >/dev/null
  docker exec "$N8N" n8n publish:workflow --id="$id" >/dev/null && echo "  ticketmoa-$n ($id) 활성"
done
docker exec "$N8N" rm -rf /tmp/ticketmoa-wf
# publish 직후 웹훅이 바로 등록된다(확인됨). 재시작은 필요할 때만 RESTART_N8N=1 로.
if [[ "${RESTART_N8N:-0}" == 1 ]]; then
  say "n8n 재시작"
  docker restart "$N8N" >/dev/null
  for i in $(seq 1 60); do [[ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 localhost:5678/healthz/readiness)" == 200 ]] && break; sleep 1; done
fi
echo "  readiness: $(curl -s -m 2 localhost:5678/healthz/readiness)"
# 다시 import 한 직후에는 웹훅이 잠시 404(재등록 중)다. 빈 질문이 400 이 될 때까지 기다린다.
smoke() { curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST localhost:5678/webhook/ticketmoa-support -H "X-Team-Key: $TM_TEAM_KEY" -H 'Content-Type: application/json' -d '{"request_id":"setup-smoke","user":"김하늘","channel":"web","question":""}'; }
code=000
for i in $(seq 1 90); do code=$(smoke); [[ "$code" == 400 ]] && break; sleep 2; done
echo "  smoke(빈 질문→400): $code ($((i*2))초)"
if [[ "$code" != 400 ]]; then
  warn "웹훅이 아직 등록되지 않았다. n8n 을 재시작한다."
  docker restart "$N8N" >/dev/null
  for i in $(seq 1 60); do [[ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 localhost:5678/healthz/readiness)" == 200 ]] && break; sleep 1; done
  sleep 5; echo "  smoke(재시작 뒤): $(smoke)"
fi

# ---------- f. 색인 ----------
if [[ "${SKIP_INDEX:-0}" != 1 ]]; then
  say "색인 (ticketmoa-index)"
  sleep 3
  out=$(curl -s -m 120 -X POST localhost:5678/webhook/ticketmoa-index -H "X-Team-Key: $TM_TEAM_KEY" -H 'Content-Type: application/json' -d '{}' || true)
  echo "  $out" | head -c 600; echo
  [[ "$OPENAI_API_KEY" == sk-placeholder ]] && warn "OpenAI 키가 placeholder 라 색인은 실패하는 것이 정상"
fi

# ---------- g. 웹앱 ----------
if [[ "${SKIP_WEBAPP:-0}" != 1 ]]; then
  say "웹앱"
  bash deploy/server/webapp.sh restart
fi

# ---------- h. 요약 ----------
say "요약"
bash deploy/server/doctor.sh
