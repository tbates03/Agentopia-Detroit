#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
export AGENTOPIA_HOME="$APP"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


export PYTHONUNBUFFERED=1
PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3 2>/dev/null || true)"
[ -n "$PY" ] || exit 30
mkdir -p "$APP/logs" "$APP/runtime/llama"
state(){ printf '%s %s\n' "$(date +%s)" "$1" > "$APP/runtime/boot_state"; }
state STARTING

# Observer first. Correct health endpoint is /api/health.
if ! curl -fsS --max-time 2 http://127.0.0.1:8766/api/health >/dev/null 2>&1; then
  nohup "$PY" "$APP/live_world/server.py" --agentopia-root "$APP" >> "$APP/logs/live-world-persistent.log" 2>&1 &
fi

# Right-Sizing / City Pulse telemetry service for the Live World performance panel.
if ! curl -fsS --max-time 2 http://127.0.0.1:8767/api/health >/dev/null 2>&1; then
  nohup "$PY" "$APP/scripts/agentopia_city_pulse.py" >> "$APP/logs/agentopia-city-pulse.log" 2>&1 &
fi

[ ! -f "$APP/scripts/backup_detroit_persistent.py" ] || "$PY" "$APP/scripts/backup_detroit_persistent.py" >> "$APP/logs/detroit-persistent-backup.log" 2>&1 || true

BACKEND=""
for ATTEMPT in 1 2; do
  state "STARTING_CORE_MODELS_$ATTEMPT"
  if "$APP/scripts/start_detroit_llama.sh" >> "$APP/logs/model-pool-bootstrap.log" 2>&1; then BACKEND=llama; break; fi
  sleep 10
done
if [ "$BACKEND" = llama ]; then
  "$PY" "$APP/scripts/select_detroit_backend.py" llama >> "$APP/logs/detroit-backend.log" 2>&1 || exit 31
else
  if command -v ollama >/dev/null 2>&1 && [ -f "$APP/data/detroit_persistent/backend_ollama_fallback.json" ]; then
    if ! curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then nohup ollama serve >> "$APP/logs/ollama-fallback.log" 2>&1 & sleep 4; fi
    "$PY" "$APP/scripts/select_detroit_backend.py" ollama >> "$APP/logs/detroit-backend.log" 2>&1 || exit 32
    BACKEND=ollama
  else
    state CORE_MODEL_START_FAILED
    exit 33
  fi
fi
printf '%s\n' "$BACKEND" > "$APP/runtime/llama/active_backend"

# Restore sidecars that were lost in the v1.6.1.1 simplified service.
if [ -f "$APP/scripts/detroit_twin_daemon.py" ] && ! pgrep -f '[d]etroit_twin_daemon.py' >/dev/null 2>&1; then
  nohup "$PY" "$APP/scripts/detroit_twin_daemon.py" >> "$APP/logs/detroit-digital-twin.log" 2>&1 &
fi
if [ -f "$APP/scripts/detroit_cognition_daemon.py" ] && ! pgrep -f '[d]etroit_cognition_daemon.py' >/dev/null 2>&1; then
  nohup "$PY" "$APP/scripts/detroit_cognition_daemon.py" >> "$APP/logs/detroit-cognition.log" 2>&1 &
fi
if [ -f "$APP/scripts/detroit_humanity_daemon.py" ] && ! pgrep -f '[d]etroit_humanity_daemon.py' >/dev/null 2>&1; then
  nohup "$PY" "$APP/scripts/detroit_humanity_daemon.py" >> "$APP/logs/detroit-humanity.log" 2>&1 &
fi

if [ -f "$APP/scripts/detroit_world_context_daemon.py" ] && ! pgrep -f '[d]etroit_world_context_daemon.py' >/dev/null 2>&1; then
  nohup "$PY" "$APP/scripts/detroit_world_context_daemon.py" >> "$APP/logs/detroit-world-context.log" 2>&1 &
fi

# Cyber is optional and never blocks the city from starting.
if [ "$BACKEND" = llama ] && ! pgrep -f '[s]tart_detroit_cyber_async.sh' >/dev/null 2>&1; then
  nohup "$APP/scripts/start_detroit_cyber_async.sh" >> "$APP/logs/cyber-async-bootstrap.log" 2>&1 &
fi

state "ENGINE_STARTING_$BACKEND"
cd "$APP" || exit 34
exec "$PY" "$APP/scripts/run_detroit_persistent.py"
