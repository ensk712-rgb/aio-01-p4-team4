#!/usr/bin/env bash
# 내 컴퓨터(macOS/Linux)의 과정용 n8n(docker 프로젝트 day65-n8n)에 티켓모아를 올린다. 멱등.
#   bash deploy/local/up.sh            # 데이터 API → Credential → 워크플로우 → 색인 → 웹앱
#   bash deploy/local/up.sh --down     # 티켓모아 데이터 API·웹앱만 내린다 (n8n 워크플로우는 비활성화)
# 전제: docker 의 day65-n8n-n8n-1 이 떠 있고, 과정용 데이터 API(day67-data-data-api-1)는 멈춰 있어야 한다
#       (같은 8800 포트와 data-api 별칭을 쓴다):  docker stop day67-data-data-api-1
# OpenAI: 로컬 .env 의 OPENAI_API_KEY 가 비어 있으면 n8n 에 이미 있는 과정용 Credential(openAiCourse0001)로 연결한다.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
N8N=day65-n8n-n8n-1
KIT="${TM_KIT_DATA_API:-$PWD/../aio-01d4-stu/Last3Mon/77/data-api}"
ORDER=(errors index search agents tech payment handoff refund ops support)
say() { printf '\n== %s\n' "$*"; }
wid() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['id'])" "$1"; }

if [[ "${1:-}" == "--down" ]]; then
  pkill -f "python3 webapp/app.py" 2>/dev/null || true
  for n in "${ORDER[@]}"; do docker exec "$N8N" n8n unpublish:workflow --id="$(wid workflows/ticketmoa-$n.json)" >/dev/null 2>&1 || true; done
  docker compose -p ticketmoa-data -f deploy/server/compose.data-api.yml down 2>&1 | tail -1
  echo "내렸다. 과정용 데이터 API 를 다시 쓰려면: docker start day67-data-data-api-1"
  exit 0
fi

docker ps --format '{{.Names}}' | grep -qx "$N8N" || { echo "$N8N 이 떠 있지 않다" >&2; exit 1; }
if docker ps --format '{{.Names}}' | grep -qx day67-data-data-api-1; then
  echo "과정용 데이터 API 가 8800 포트를 쓰고 있다. 먼저:  docker stop day67-data-data-api-1" >&2; exit 1
fi

say "데이터 API 파일 (tools/data-api)"
[[ -f "$KIT/server.py" ]] || { echo "키트를 찾지 못함: $KIT (TM_KIT_DATA_API)" >&2; exit 1; }
mkdir -p tools/data-api && cp "$KIT/server.py" tools/data-api/server.py
rm -rf tools/data-api/data && mkdir -p tools/data-api/data && cp -R "$KIT/data/." tools/data-api/data/
cp data/users.json tools/data-api/data/employees.json && cp data/records.json tools/data-api/data/tickets.json
rm -rf tools/data-api/data/docs && mkdir -p tools/data-api/data/docs && cp knowledge/*.md tools/data-api/data/docs/
# data/ 를 지우고 다시 만들었으므로 떠 있던 컨테이너는 옛 폴더를 본다. 다시 만들어 새 바인드 마운트를 잡는다.
docker compose -p ticketmoa-data -f deploy/server/compose.data-api.yml up -d --force-recreate 2>&1 | tail -1
for i in $(seq 1 30); do curl -sf -m 2 localhost:8800/health >/dev/null && break; sleep 1; done
echo "  호스트 $(curl -s -m 2 localhost:8800/health) / n8n에서 $(docker exec "$N8N" wget -qO- -T 3 http://data-api:8800/health 2>&1 || echo FAIL)"

say ".env"
[[ -f .env ]] || cp .env.example .env
chmod 600 .env
getenv() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
if [[ -z "$(getenv TM_TEAM_KEY)" ]]; then
  python3 - <<'PY'
import re,secrets
t=open('.env').read()
t=re.sub(r'^TM_TEAM_KEY=\s*$','TM_TEAM_KEY=tm-local-'+secrets.token_hex(12),t,flags=re.M) if re.search(r'^TM_TEAM_KEY=',t,re.M) else t+'\nTM_TEAM_KEY=tm-local-'+secrets.token_hex(12)+'\n'
open('.env','w').write(t)
PY
  echo "  TM_TEAM_KEY 를 난수로 만들었다"
fi
[[ -z "$(getenv TM_DATA_API_KEY)" ]] && echo "TM_DATA_API_KEY=ticketmoa-data" >> .env
set -a; . ./.env; set +a
OPENAI_REMAP=0; [[ -z "${OPENAI_API_KEY:-}" ]] && OPENAI_REMAP=1

say "Credential import"
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
OPENAI_REMAP=$OPENAI_REMAP python3 - "$TMP" <<'PY'
import json,os,sys
creds=[{"id":"ticketmoaDataApi1","name":"ticketmoa-data-api","type":"httpHeaderAuth","data":{"name":"X-Api-Key","value":os.environ.get("TM_DATA_API_KEY","ticketmoa-data")}},
       {"id":"ticketmoaTeamKey1","name":"ticketmoa-team-key","type":"httpHeaderAuth","data":{"name":"X-Team-Key","value":os.environ["TM_TEAM_KEY"]}}]
if os.environ["OPENAI_REMAP"]=="0":
    creds.append({"id":"ticketmoaOpenAi01","name":"OpenAI","type":"openAiApi","data":{"apiKey":os.environ["OPENAI_API_KEY"],"url":"https://api.openai.com/v1"}})
open(sys.argv[1],"w").write(json.dumps(creds))
PY
docker exec -u root "$N8N" rm -f /tmp/tm-creds.json
docker cp "$TMP" "$N8N:/tmp/tm-creds.json" && docker exec -u root "$N8N" chown node:node /tmp/tm-creds.json
docker exec "$N8N" n8n import:credentials --input=/tmp/tm-creds.json | tail -1
docker exec -u root "$N8N" rm -f /tmp/tm-creds.json; rm -f "$TMP"
[[ $OPENAI_REMAP == 1 ]] && echo "  OPENAI_API_KEY 가 비어 있어 과정용 Credential openAiCourse0001 로 연결한다"

say "워크플로우 import·publish"
WF=$(mktemp -d); trap 'rm -rf "$WF" "$TMP"' EXIT
OPENAI_REMAP=$OPENAI_REMAP python3 - "$WF" <<'PY'
import json,sys,glob,os
out=sys.argv[1]; remap=os.environ["OPENAI_REMAP"]=="1"
for f in sorted(glob.glob('workflows/ticketmoa-*.json')):
    w=json.load(open(f))
    if remap:
        for node in w['nodes']:
            c=(node.get('credentials') or {}).get('openAiApi')
            if c and c.get('id')=='ticketmoaOpenAi01': c['id']='openAiCourse0001'; c['name']='OpenAI (.env)'
    json.dump(w,open(os.path.join(out,os.path.basename(f)),'w'),ensure_ascii=False)
PY
docker exec -u root "$N8N" rm -rf /tmp/tm-wf; docker exec "$N8N" mkdir -p /tmp/tm-wf
docker cp "$WF/." "$N8N:/tmp/tm-wf/" && docker exec -u root "$N8N" chown -R node:node /tmp/tm-wf
for n in "${ORDER[@]}"; do
  docker exec "$N8N" n8n import:workflow --input="/tmp/tm-wf/ticketmoa-$n.json" >/dev/null
  docker exec "$N8N" n8n publish:workflow --id="$(wid workflows/ticketmoa-$n.json)" >/dev/null && echo -n "$n "
done; echo
docker exec -u root "$N8N" rm -rf /tmp/tm-wf
smoke() { curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST localhost:5678/webhook/ticketmoa-support -H "X-Team-Key: $TM_TEAM_KEY" -H 'Content-Type: application/json' -d '{"request_id":"local-smoke","user":"김하늘","channel":"web","question":""}'; }
for i in $(seq 1 60); do code=$(smoke); [[ "$code" == 400 ]] && break; sleep 2; done
echo "  smoke(빈 질문→400): $code"
[[ "$code" == 400 ]] || { echo "smoke 실패: 빈 질문이 400이 아니다 (데이터 API·워크플로우 확인)" >&2; exit 1; }

say "색인"
python3 deploy/server/run-cases.py --index | tail -2

say "웹앱 (http://localhost:${TM_PORT:-8080})"
pkill -f "python3 webapp/app.py" 2>/dev/null || true
mkdir -p runs
(set -a; . ./.env; set +a; nohup python3 webapp/app.py >> runs/webapp-local.log 2>&1 &)
sleep 2; curl -s -m 5 "localhost:${TM_PORT:-8080}/api/status"; echo
echo "n8n: http://localhost:5678/home/workflows   시험: python3 deploy/server/run-cases.py --suite all -v"
