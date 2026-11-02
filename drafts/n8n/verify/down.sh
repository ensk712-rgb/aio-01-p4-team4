#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Explicit project/file: no global docker prune or course-container operation.
docker compose -p ticketmoa-verify -f compose.yml down --volumes --remove-orphans
