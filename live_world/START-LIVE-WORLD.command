#!/bin/bash
set -u

APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
LIVE="$APP/live_world"
SIM_LOG="$LIVE/agentopia-simulation.log"
SIM_PID_FILE="$LIVE/agentopia-simulation.pid"
PORT=8766

clear 2>/dev/null || true
echo ""
echo "=============================================================="
echo "       AGENTOPIA DETROIT LIVE WORLD v0.7 - INTERIORS"
echo "=============================================================="
echo ""

if [ ! -d "$APP/data" ]; then
  echo "ERROR: Agentopia was not found at:"
  echo "  $APP"
  exit 1
fi

if [ -x "$APP/.venv/bin/python" ]; then
  PY="$APP/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "ERROR: Python 3 not found."
  exit 1
fi

WORLD="apartment"
MAX_AGENTS=8
if [ -d "$APP/data/detroit/persona" ]; then
  WORLD="detroit"
  MAX_AGENTS=24
fi

if open -Ra "Ollama" >/dev/null 2>&1; then
  open -a "Ollama" >/dev/null 2>&1 || true
fi

if pgrep -f "scripts/run_world.py" >/dev/null 2>&1; then
  echo "Agentopia simulation: already running"
else
  echo "Agentopia simulation: starting $WORLD"
  echo "  active agents: $MAX_AGENTS"
  cd "$APP" || exit 1
  : > "$SIM_LOG"
  nohup "$PY" scripts/run_world.py --world "$WORLD" --years 1 --weeks 2 --max-agents "$MAX_AGENTS" >> "$SIM_LOG" 2>&1 &
  SIM_PID=$!
  echo "$SIM_PID" > "$SIM_PID_FILE"
  sleep 2
  if ! kill -0 "$SIM_PID" >/dev/null 2>&1; then
    echo ""
    echo "Agentopia stopped during startup. Last log lines:"
    echo "--------------------------------------------------------------"
    tail -n 60 "$SIM_LOG" 2>/dev/null || true
    echo "--------------------------------------------------------------"
    exit 1
  fi
  echo "Agentopia PID: $SIM_PID"
fi

echo "Dashboard: http://127.0.0.1:$PORT"
echo "Click any building to enter its live Interior View."
echo ""

if command -v lsof >/dev/null 2>&1; then
  for PID in $(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true); do
    CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    case "$CMD" in
      *live_world/server.py*) kill "$PID" 2>/dev/null || true; sleep 1 ;;
    esac
  done
fi

cd "$LIVE" || exit 1
exec "$PY" "$LIVE/server.py" --agentopia-root "$APP"
