#!/usr/bin/env bash
# 로컬(macOS/Linux) → 서버 aio-t4 동기화. Windows는 deploy/push.ps1.
#   bash deploy/push.sh            # 파일만 올린다
#   bash deploy/push.sh --setup    # 올린 뒤 서버에서 deploy/server/setup.sh 까지 실행
# 환경변수: TM_SSH_HOST(기본 aio-t4), TM_KIT_DATA_API(기본 ../aio-01d4-stu/Last3Mon/77/data-api)
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${TM_SSH_HOST:-aio-t4}"
KIT="${TM_KIT_DATA_API:-$ROOT/../aio-01d4-stu/Last3Mon/77/data-api}"
REMOTE='~/aio-01-p4-team4'
SETUP=0
[[ "${1:-}" == "--setup" ]] && SETUP=1

cd "$ROOT"
echo "== 저장소 파일 → $HOST:$REMOTE"
ssh "$HOST" "mkdir -p $REMOTE/tools/data-api $REMOTE/runs"
for dir in workflows lib data knowledge cases requests config webapp deploy; do
  [[ -d "$dir" ]] || { echo "  (없음, 건너뜀) $dir"; continue; }
  # PDF 등 지식 문서가 아닌 파일은 올리지 않는다.
  if [[ "$dir" == "knowledge" ]]; then
    ssh "$HOST" "mkdir -p $REMOTE/knowledge"
    scp -q knowledge/*.md "$HOST:$REMOTE/knowledge/"
  else
    scp -rq "$dir" "$HOST:$REMOTE/"
  fi
  echo "  $dir"
done

echo "== 과정 키트 데이터 API → $HOST:$REMOTE/tools/data-api"
[[ -f "$KIT/server.py" && -d "$KIT/data" ]] || { echo "키트를 찾지 못함: $KIT (TM_KIT_DATA_API 로 지정)" >&2; exit 1; }
scp -q "$KIT/server.py" "$HOST:$REMOTE/tools/data-api/server.py"
ssh "$HOST" "mkdir -p $REMOTE/tools/data-api/kit-data"
scp -rq "$KIT/data/." "$HOST:$REMOTE/tools/data-api/kit-data/"

if [[ -f "$ROOT/.env" ]]; then
  echo "== .env → 서버 (git에는 올리지 않음)"
  scp -q "$ROOT/.env" "$HOST:$REMOTE/.env"
else
  echo "== 로컬 .env 없음. 서버 .env 는 그대로 둔다 (없으면 setup.sh 가 만든다)."
fi

if [[ $SETUP -eq 1 ]]; then
  echo "== 서버 setup.sh 실행"
  ssh "$HOST" "bash -lc 'cd $REMOTE && bash deploy/server/setup.sh'"
else
  echo "다음: ssh $HOST \"bash -lc 'cd $REMOTE && bash deploy/server/setup.sh'\""
fi
