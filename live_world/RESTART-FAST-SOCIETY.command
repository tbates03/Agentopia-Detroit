#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
LIVE="$APP/live_world"
PIDFILE="$LIVE/agentopia-simulation.pid"
LOG="$LIVE/agentopia-simulation.log"
PY="$APP/.venv/bin/python"

clear
echo "Restarting the Live World-managed Agentopia society..."
echo ""

# Only stop a process whose PID was written by our own launcher.
if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    case "$CMD" in
      *scripts/run_world.py*)
        echo "Stopping managed Agentopia PID $PID safely..."
        kill -TERM "$PID" 2>/dev/null || true
        for i in $(seq 1 12); do
          kill -0 "$PID" 2>/dev/null || break
          sleep 1
        done
        ;;
      *) echo "PID file does not point to Agentopia; leaving process untouched." ;;
    esac
  fi
fi

if pgrep -f "scripts/run_world.py" >/dev/null 2>&1; then
  echo ""
  echo "Another Agentopia simulation is still running."
  echo "It was not started by this launcher, so I will not kill it automatically."
  echo "Live World will follow that active run instead."
else
  cd "$APP" || exit 1
  : > "$LOG"
  nohup "$PY" scripts/run_world.py --world apartment --years 1 --weeks 2 --max-agents 8 >> "$LOG" 2>&1 &
  PID=$!
  echo "$PID" > "$PIDFILE"
  echo "Started 8-agent fast society as PID $PID."
fi

echo ""
echo "Opening Live World..."
open "http://127.0.0.1:8766" >/dev/null 2>&1 || true
read -r -p "Press ENTER to close..."
