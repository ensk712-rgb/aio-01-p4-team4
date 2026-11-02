#!/usr/bin/env bash
# 워크플로우만 다시 넣는다. API·mock 상태는 유지하되 n8n 재시작으로 In-Memory 색인이 비므로 다시 색인한다.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
C="docker compose -p ticketmoa-verify -f compose.yml"
python3 - <<'PY' > ./.order.tsv
import json,pathlib
for name in ['errors','index','search','agents','tech','payment','handoff','refund','ops','support']:
    p=pathlib.Path('../../../workflows')/f'ticketmoa-{name}.json'
    print(p.name,json.loads(p.read_text())['id'],sep='\t')
PY
while IFS=$'\t' read -r file id; do
  $C exec -T n8n n8n import:workflow --input="/verify-workflows/$file" </dev/null >/dev/null
  $C exec -T n8n n8n publish:workflow --id="$id" </dev/null >/dev/null
done < ./.order.tsv
$C restart n8n >/dev/null 2>&1
python3 -B runner.py --wait-ready
python3 -B runner.py --index
