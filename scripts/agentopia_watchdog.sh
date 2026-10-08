#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LABEL=com.agentopia.detroit.persistent
DOMAIN="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
STATE="$APP/runtime/boot_state"
LOG="$APP/logs/agentopia-watchdog.log"
mkdir -p "$APP/logs" "$APP/runtime"
model_health(){ curl -fsS --max-time 3 "http://127.0.0.1:$1/health" >/dev/null 2>&1; }
web_health(){ curl -fsS --max-time 3 http://127.0.0.1:8766/api/health >/dev/null 2>&1; }
pulse_health(){ curl -fsS --max-time 3 http://127.0.0.1:8767/api/health >/dev/null 2>&1; }
log(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

if [ -f "$STATE" ]; then
  started="$(awk 'NR==1{print $1}' "$STATE" 2>/dev/null || echo 0)"
  phase="$(awk 'NR==1{print $2}' "$STATE" 2>/dev/null || echo unknown)"
  case "$started" in ''|*[!0-9]*) started=0;; esac
  age=$(( $(date +%s) - started ))
  case "$phase" in STARTING*|ENGINE_STARTING*) [ "$age" -lt 600 ] && exit 0;; esac
fi

engine=0; pgrep -f '[r]un_detroit_persistent.py' >/dev/null 2>&1 && engine=1
backend="$(cat "$APP/runtime/llama/active_backend" 2>/dev/null || echo unknown)"
core=1
if [ "$backend" = llama ]; then
  model_health 8084 || core=0; model_health 8081 || core=0; model_health 8082 || core=0
fi
if [ "$engine" -ne 1 ] || [ "$core" -ne 1 ]; then
  log "recovery engine=$engine backend=$backend core=$core"
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || launchctl bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
  launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  exit 0
fi
if ! web_health; then
  PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3 2>/dev/null || true)"
  [ -z "$PY" ] || nohup "$PY" "$APP/live_world/server.py" --agentopia-root "$APP" >> "$APP/logs/live-world-persistent.log" 2>&1 &
fi
if ! pulse_health; then
  PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3 2>/dev/null || true)"
  [ -z "$PY" ] || nohup "$PY" "$APP/scripts/agentopia_city_pulse.py" >> "$APP/logs/agentopia-city-pulse.log" 2>&1 &
fi
if model_health 8083; then touch "$APP/runtime/llama/cyber_available"; else rm -f "$APP/runtime/llama/cyber_available"; fi
