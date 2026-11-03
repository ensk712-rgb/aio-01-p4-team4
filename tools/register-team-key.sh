#!/usr/bin/env bash
# 팀 웹훅 Header Auth Credential을 고정 id로 n8n에 넣는다 (팀원 모두 같은 id라야 JSON이 그대로 돈다).
#   TEAM_KEY=<팀 키> bash tools/register-team-key.sh
#   N8N_CONTAINER=<이름>  (기본 day65-n8n-n8n-1)
# 키 값은 저장소·문서에 쓰지 않는다. 셸에서만 넣는다.
set -euo pipefail
key="${TEAM_KEY:-}"
if [ -z "$key" ]; then read -r -s -p "팀 키: " key; echo; fi
[ -n "$key" ] || { echo "TEAM_KEY가 비어 있다." >&2; exit 1; }
case "$key" in *\"*|*\\*) echo "키에 \" 나 \\ 는 쓸 수 없다." >&2; exit 1;; esac

credentials=$(printf '[{"id":"ticketmoaTeamKey1","name":"ticketmoa-team-key","type":"httpHeaderAuth","data":{"name":"X-Team-Key","value":"%s"}}]' "$key")
container="${N8N_CONTAINER:-day65-n8n-n8n-1}"
docker inspect "$container" >/dev/null 2>&1 || { echo "n8n 컨테이너 '$container'가 없다 (docker ps로 이름 확인)." >&2; exit 1; }
printf '%s' "$credentials" | docker exec -i "$container" sh -c \
  'cat > /tmp/team-key.json && n8n import:credentials --input=/tmp/team-key.json; status=$?; rm -f /tmp/team-key.json; exit $status'
echo "Registered 'ticketmoa-team-key' (ticketmoaTeamKey1)"
