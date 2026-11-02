#!/usr/bin/env bash
# 서버에서 웹앱을 tmux 세션(ticketmoa-webapp)으로 띄운다.
#   bash deploy/server/webapp.sh start|stop|restart|status|log
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
SESSION=ticketmoa-webapp
LOG=runs/webapp.log
cmd="${1:-status}"

running() { tmux has-session -t "$SESSION" 2>/dev/null; }
port() { grep -E '^TM_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }

case "$cmd" in
  start)
    [[ -f webapp/app.py ]] || { echo "  webapp/app.py 없음, 건너뜀"; exit 0; }
    if running; then echo "  이미 실행 중 (tmux $SESSION)"; exit 0; fi
    mkdir -p runs
    tmux new-session -d -s "$SESSION" "cd '$(pwd)' && set -a && . ./.env && set +a && exec python3 webapp/app.py >> '$LOG' 2>&1"
    sleep 1
    echo "  시작: tmux $SESSION, 포트 ${TM_PORT:-$(port)}"
    ;;
  stop)
    if running; then tmux kill-session -t "$SESSION"; echo "  중지"; else echo "  실행 중 아님"; fi
    ;;
  restart)
    bash "$0" stop; bash "$0" start
    ;;
  status)
    if running; then
      p="${TM_PORT:-$(port)}"; p="${p:-8080}"
      echo "  실행 중 (tmux $SESSION), http://127.0.0.1:$p → $(curl -s -o /dev/null -w '%{http_code}' -m 2 "http://127.0.0.1:$p/" || echo 000)"
    else
      echo "  실행 중 아님"
    fi
    ;;
  log)
    tail -n 50 "$LOG"
    ;;
  *) echo "사용: $0 start|stop|restart|status|log"; exit 2;;
esac
