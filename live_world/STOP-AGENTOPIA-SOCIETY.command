#!/bin/bash
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
LIVE="$APP/live_world"
PID_FILE="$LIVE/agentopia-simulation.pid"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID"
    echo "Stopped Agentopia simulation PID $PID"
  else
    echo "Saved Agentopia PID is not running."
  fi
  rm -f "$PID_FILE"
else
  echo "No managed Agentopia simulation PID file found."
fi
