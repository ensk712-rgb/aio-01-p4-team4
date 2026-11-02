#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Refuse missing/ambiguous IDs before creating anything.
python3 - <<'PY'
import json,pathlib
files=list(pathlib.Path('../../../workflows').glob('*.json'))
expected={'support','agents','refund','index','search','tech','payment','handoff','errors','ops'}
assert {p.stem.removeprefix('ticketmoa-') for p in files} == expected, 'Need exactly ten workflow JSON files'
ids=[json.loads(p.read_text()).get('id') for p in files]
assert all(ids) and len(set(ids))==10, 'Workflow IDs must exist and be unique'
PY
./prepare-data.sh
docker compose -p ticketmoa-verify -f compose.yml up -d
python3 runner.py --wait-ready
./register-credentials.sh
# Import and publish each actual ID; errors first, support last.
while IFS=$'\t' read -r file id; do
  docker compose -p ticketmoa-verify -f compose.yml exec -T n8n n8n import:workflow --input="/verify-workflows/$file" </dev/null
  docker compose -p ticketmoa-verify -f compose.yml exec -T n8n n8n publish:workflow --id="$id" </dev/null
done < <(python3 - <<'PY'
import json,pathlib
order=['errors','index','search','agents','tech','payment','handoff','refund','ops','support']
for name in order:
 p=pathlib.Path('../../../workflows')/f'ticketmoa-{name}.json'
 print(p.name,json.loads(p.read_text())['id'],sep='\t')
PY
)
docker compose -p ticketmoa-verify -f compose.yml restart n8n
python3 runner.py --wait-ready
# Must be measured in a fresh n8n process BEFORE index runs.
python3 runner.py --pre-index
python3 runner.py --index
echo 'Ready. Run: python3 runner.py --suite all --repeat 1'
