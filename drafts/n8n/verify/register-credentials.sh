#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
docker compose -p ticketmoa-verify -f compose.yml exec -T n8n n8n import:credentials --input=/verify-credentials.json
