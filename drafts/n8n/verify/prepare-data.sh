#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SOURCE="$ROOT/../aio-01d4-stu/Last3Mon/77/data-api/data"
# Only this harness's generated fixture is replaced; never edit the course kit.
[[ -f "$SOURCE/tickets.json" ]] || { echo "77 data fixture missing" >&2; exit 1; }
mkdir -p "$HERE/runtime-data"
cp -R "$SOURCE/." "$HERE/runtime-data/"
cp "$ROOT/data/users.json" "$HERE/runtime-data/employees.json"
cp "$ROOT/data/records.json" "$HERE/runtime-data/tickets.json"
rm -rf -- "$HERE/runtime-data/docs"
mkdir -p "$HERE/runtime-data/docs"
cp "$ROOT"/knowledge/*.md "$HERE/runtime-data/docs/"
echo "Prepared isolated fixtures (dates unchanged)."
