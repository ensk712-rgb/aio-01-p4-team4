#!/usr/bin/env bash
# 서버 상태 한눈에 보기. 비밀값은 출력하지 않는다.
#   cd ~/aio-01-p4-team4 && bash deploy/server/doctor.sh
set -uo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
N8N=day65-n8n-n8n-1

echo "[컨테이너]"
docker ps --format '  {{.Names}}  {{.Status}}' | grep -E 'n8n-n8n|data-api|runners' || echo "  (없음)"
echo "[데이터 API]"
echo "  호스트  : $(curl -s -m 2 localhost:8800/health || echo FAIL)"
echo "  n8n에서 : $(docker exec "$N8N" wget -qO- -T 3 http://data-api:8800/health 2>/dev/null || echo FAIL)"
echo "  티켓 $(curl -s -m 2 localhost:8800/tickets-created | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])' 2>/dev/null || echo ?)건, DLQ $(curl -s -m 2 localhost:8800/dlq | python3 -c 'import json,sys;print(json.load(sys.stdin)["size"])' 2>/dev/null || echo ?)건, 알림 $(curl -s -m 2 localhost:8800/alerts | python3 -c 'import json,sys;print(json.load(sys.stdin)["count"])' 2>/dev/null || echo ?)건"
echo "[n8n]"
echo "  readiness: $(curl -s -m 2 localhost:5678/healthz/readiness || echo FAIL)"
docker exec "$N8N" n8n export:workflow --all 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read(); i=raw.find("[")
ws=json.loads(raw[i:]) if i>=0 else []
ws=[w for w in ws if str(w.get("name","")).startswith("ticketmoa")]
active=sum(1 for w in ws if w.get("active"))
names=", ".join(w["name"]+("" if w.get("active") else "(비활성)") for w in sorted(ws,key=lambda w:w["name"]))
print(f"  워크플로우 {len(ws)}개 (활성 {active}개): {names}")' 2>/dev/null || echo "  워크플로우 목록 실패"
docker exec "$N8N" n8n export:credentials --all 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read(); i=raw.find("[")
cs=json.loads(raw[i:]) if i>=0 else []
names={c.get("id"):c.get("name") for c in cs}
want={"ticketmoaOpenAi01":"OpenAI","ticketmoaDataApi1":"ticketmoa-data-api","ticketmoaTeamKey1":"ticketmoa-team-key"}
print("  Credential: "+", ".join(v+(" OK" if names.get(k)==v else " 없음") for k,v in want.items()))' 2>/dev/null || echo "  Credential 목록 실패"
if grep -qE '^OPENAI_API_KEY=sk-placeholder' .env 2>/dev/null; then echo "  !! OPENAI_API_KEY 가 placeholder (LLM·색인 불가)"; fi
echo "[웹앱]"
bash deploy/server/webapp.sh status
echo "[메모리]"
free -h | sed -n 2p | awk '{print "  총 "$2", 사용 "$3", 가용 "$7}'
echo "[접속]  ssh -L 8080:localhost:8080 -L 5678:localhost:5678 aio-t4   → 웹앱 http://localhost:8080, n8n http://localhost:5678"
