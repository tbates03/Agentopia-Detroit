#!/bin/bash
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
for N in citizen strategy cyber; do
  P="$APP/runtime/llama/$N.pid"
  if [ -f "$P" ]; then
    PID="$(cat "$P" 2>/dev/null || true)"
    [ -z "$PID" ] || kill -TERM "$PID" 2>/dev/null || true
    rm -f "$P"
  fi
done
