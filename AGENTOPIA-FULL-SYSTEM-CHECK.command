#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
VER="$(cat "$APP/VERSION" 2>/dev/null || echo unknown)"
WORLD="$APP/data/detroit_persistent"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
FAIL=0; WARN=0
ok(){ echo "OK   $*"; }; bad(){ echo "FAIL $*"; FAIL=$((FAIL+1)); }; warn(){ echo "WARN $*"; WARN=$((WARN+1)); }
model_health(){ curl -fsS --max-time 3 "http://127.0.0.1:$1/health" >/dev/null 2>&1; }
web_health(){ curl -fsS --max-time 3 http://127.0.0.1:8766/api/health >/dev/null 2>&1; }
echo "AGENTOPIA DETROIT v$VER FULL SYSTEM CHECK"
echo "$(date)"
[ -d "$WORLD/persona" ] && ok "Persistent persona store" || bad "Persistent persona store missing"
[ -f "$WORLD/config.json" ] && ok "World config" || bad "World config missing"
[ -f "$WORLD/checkpoint.json" ] && ok "Checkpoint" || warn "Checkpoint missing"
[ -d "$WORLD/mission_justice" ] && ok "Mission/Justice state" || warn "Mission/Justice state not detected"
[ -f "$WORLD/finance/summary.json" ] && ok "Financial Network state" || warn "Financial summary not detected"
[ -f "$WORLD/career/summary.json" ] && ok "Career Economy state (200 professions)" || warn "Career Economy summary not detected"
[ -f "$WORLD/business_economy/summary.json" ] && ok "Business Economy state" || warn "Business Economy summary not detected"
[ -f "$WORLD/human_economy/summary.json" ] && ok "Human Economy state" || warn "Human Economy summary not detected"
launchctl print "gui/$(id -u)/com.agentopia.detroit.persistent" >/dev/null 2>&1 && ok "Primary LaunchAgent loaded" || bad "Primary LaunchAgent missing"
launchctl print "gui/$(id -u)/com.agentopia.detroit.watchdog" >/dev/null 2>&1 && ok "Watchdog loaded" || warn "Watchdog missing"
COUNT="$(pgrep -f '[r]un_detroit_persistent.py' 2>/dev/null | wc -l | tr -d ' ')"
[ "$COUNT" = 1 ] && ok "Exactly one Detroit engine" || bad "Detroit engine count=$COUNT"
backend="$(cat "$APP/runtime/llama/active_backend" 2>/dev/null || echo unknown)"
ok "Backend=$backend"
if [ "$backend" = llama ]; then
 model_health 8084 && ok "Social 350M :8084" || bad "Social 350M down"
 model_health 8081 && ok "Citizen 1.2B :8081" || bad "Citizen 1.2B down"
 model_health 8082 && ok "Strategy 2.6B :8082" || bad "Strategy 2.6B down"
 model_health 8083 && ok "Cyber 7B :8083" || warn "Cyber 7B down; strategy fallback active"
elif [ "$backend" = ollama ]; then
 curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && ok "Ollama fallback" || bad "Ollama fallback unavailable"
else bad "Backend marker unknown"; fi
web_health && ok "Live World /api/health" || bad "Live World down"
for P in detroit_twin_daemon.py detroit_cognition_daemon.py detroit_humanity_daemon.py; do
  if [ -f "$APP/scripts/$P" ]; then pgrep -f "[${P:0:1}]${P:1}" >/dev/null 2>&1 && ok "$P" || warn "$P not running"; fi
done
if [ -f "$APP/runtime/engine_heartbeat.json" ]; then
 AGE=$(( $(date +%s) - $(stat -f %m "$APP/runtime/engine_heartbeat.json" 2>/dev/null || echo 0) ))
 [ "$AGE" -lt 20 ] && ok "Engine heartbeat age=${AGE}s" || bad "Engine heartbeat stale age=${AGE}s"
else bad "Engine heartbeat missing"; fi
[ -f "$APP/runtime/boot_state" ] && ok "Boot state: $(cat "$APP/runtime/boot_state")" || warn "Boot state missing"
for S in "$APP/scripts/start_detroit_persistent_service.sh" "$APP/scripts/start_detroit_llama.sh" "$APP/scripts/start_detroit_cyber_async.sh" "$APP/scripts/agentopia_watchdog.sh"; do bash -n "$S" >/dev/null 2>&1 && ok "Syntax $(basename "$S")" || bad "Syntax $(basename "$S")"; done
echo
echo "Recent engine activity:"
tail -12 "$APP/logs/detroit-persistent-launchd-error.log" 2>/dev/null || true
echo
# AGENTOPIA_PLATFORM_VERSION_CHECK_V172_START
EXPECTED_PLATFORM_VERSION="1.7.2"
ACTUAL_PLATFORM_VERSION="$(cat "$APP/VERSION" 2>/dev/null || true)"
[ "$ACTUAL_PLATFORM_VERSION" = "$EXPECTED_PLATFORM_VERSION" ] && ok "Platform release v$ACTUAL_PLATFORM_VERSION" || warn "Platform release mismatch expected=$EXPECTED_PLATFORM_VERSION actual=${ACTUAL_PLATFORM_VERSION:-missing}"
[ -f "$WORLD/education/summary.json" ] && ok "Education & Skills Economy state" || warn "Education & Skills Economy summary not detected"
[ -f "$WORLD/healthcare/summary.json" ] && ok "Health & Healthcare Economy state" || warn "Health & Healthcare Economy summary not detected"
[ -f "$WORLD/mobility/summary.json" ] && ok "Mobility & Time state" || warn "Mobility & Time summary not detected"
grep -q "agentopiaReleaseVersion" "$APP/live_world/static/index.html" 2>/dev/null && grep -q "$VER" "$APP/live_world/static/index.html" 2>/dev/null && ok "Live World footer version v$VER" || warn "Live World footer version mismatch"
# AGENTOPIA_PLATFORM_VERSION_CHECK_V172_END

if [ "$FAIL" -eq 0 ]; then echo "RESULT: PASS ($WARN warning(s))"; exit 0; fi
echo "RESULT: FAIL ($FAIL failure(s), $WARN warning(s))"; exit 1
