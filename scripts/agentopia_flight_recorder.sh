#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
WORLD="$APP/data/detroit_persistent"
LOCK="/tmp/agentopia-flight-recorder-${UID}.lock"
PIDFILE="$LOCK/pid"
mkdir -p "$APP/logs"

# ANSI palette. Only the observer console is colored; log files remain raw.
RESET=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RED=$'\033[1;31m'
GREEN=$'\033[1;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[1;34m'
MAGENTA=$'\033[1;35m'
CYAN=$'\033[1;36m'
WHITE=$'\033[1;37m'

if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -f "$PIDFILE" ]; then
    OLD="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
      printf '%sAgentopia Flight Recorder is already running as PID %s%s\n' "$YELLOW" "$OLD" "$RESET"
      exit 0
    fi
  fi
  rm -rf "$LOCK" 2>/dev/null || true
  mkdir "$LOCK" || exit 1
fi

echo $$ > "$PIDFILE"
cleanup(){ rm -rf "$LOCK" 2>/dev/null || true; [ -n "${STATUS_PID:-}" ] && kill "$STATUS_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

printf '\033]0;Agentopia Detroit - Flight Recorder\007'
printf '%s================================================================%s\n' "$CYAN" "$RESET"
printf '%s AGENTOPIA DETROIT - FLIGHT RECORDER%s\n' "$BOLD$WHITE" "$RESET"
printf ' %sGOOD%s  %sWARNING%s  %sBAD%s  %sGUARDIAN%s  %sOBSIDIAN/CRIME%s  %sSTAGE/INFO%s\n' "$GREEN" "$RESET" "$YELLOW" "$RESET" "$RED" "$RESET" "$BLUE" "$RESET" "$MAGENTA" "$RESET" "$CYAN" "$RESET"
printf ' Console + raw event streams. Ctrl-C stops recorder only.\n'
printf '%s================================================================%s\n' "$CYAN" "$RESET"

status_line(){
  local label="$1" color="$2" value="$3"
  printf '%-11s: %s%s%s\n' "$label" "$color" "$value" "$RESET"
}

port_status(){
  local label="$1" url="$2"
  if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
    status_line "$label" "$GREEN" "ONLINE"
  else
    status_line "$label" "$RED" "OFFLINE"
  fi
}

audit_once(){
  printf '\n%s----- STATUS %s -----%s\n' "$CYAN" "$(date '+%Y-%m-%d %H:%M:%S')" "$RESET"

  VER="$(cat "$APP/VERSION" 2>/dev/null || echo '?')"
  status_line "VERSION" "$CYAN" "$VER"

  EPID="$(pgrep -f '[r]un_detroit_persistent.py' | head -1 || true)"
  if [ -n "$EPID" ]; then
    ETIME="$(ps -p "$EPID" -o etime= 2>/dev/null | xargs || true)"
    status_line "ENGINE" "$GREEN" "RUNNING pid=$EPID elapsed=${ETIME:-?}"
  else
    status_line "ENGINE" "$RED" "STOPPED"
  fi

  CP="$(cat "$WORLD/checkpoint.json" 2>/dev/null || true)"
  if [ -n "$CP" ]; then status_line "CHECKPOINT" "$CYAN" "$CP"; else status_line "CHECKPOINT" "$RED" "MISSING"; fi

  if [ -f "$APP/runtime/engine_heartbeat.json" ]; then
    HB="$(python3 - "$APP/runtime/engine_heartbeat.json" 2>/dev/null <<'PY'
import json,sys,time
try:
    d=json.load(open(sys.argv[1])); age=max(0.0,time.time()-float(d.get('unix',0)))
    print(f"{age:.1f}|{d.get('pid','?')}|{d.get('version','?')}")
except Exception:
    print("999999|?|?")
PY
)"
    AGE="${HB%%|*}"; REST="${HB#*|}"; HPID="${REST%%|*}"; HVER="${REST#*|}"
    HB_COLOR="$GREEN"
    python3 - "$AGE" <<'PY' >/dev/null 2>&1 || HB_COLOR="$RED"
import sys
raise SystemExit(0 if float(sys.argv[1]) <= 10 else 1)
PY
    if [ "$HB_COLOR" = "$RED" ]; then
      python3 - "$AGE" <<'PY' >/dev/null 2>&1 && HB_COLOR="$YELLOW"
import sys
raise SystemExit(0 if float(sys.argv[1]) <= 30 else 1)
PY
    fi
    status_line "HEARTBEAT" "$HB_COLOR" "${AGE}s old | pid=$HPID | version=$HVER"
  else
    status_line "HEARTBEAT" "$RED" "MISSING"
  fi

  port_status "MODEL 8084" "http://127.0.0.1:8084/health"
  port_status "MODEL 8081" "http://127.0.0.1:8081/health"
  port_status "MODEL 8082" "http://127.0.0.1:8082/health"
  port_status "MODEL 8083" "http://127.0.0.1:8083/health"
  port_status "LIVE 8766"  "http://127.0.0.1:8766/api/health"

  curl -fsS --max-time 3 "http://127.0.0.1:8766/api/snapshot?run=detroit_persistent" -o "$APP/logs/flight-recorder-snapshot.json.tmp" 2>/dev/null && mv "$APP/logs/flight-recorder-snapshot.json.tmp" "$APP/logs/flight-recorder-snapshot.json" 2>/dev/null || true

  python3 - "$WORLD" <<'PY'
import json,sys
from pathlib import Path
w=Path(sys.argv[1])
G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;34m'; M='\033[1;35m'; C='\033[1;36m'; X='\033[0m'
def rd(p):
    try:return json.loads(p.read_text())
    except:return {}
m=rd(w/'mission_justice'/'summary.json'); f=rd(w/'finance'/'summary.json'); e=rd(w/'human_economy'/'summary.json'); h=rd(w/'humanity'/'summary.json')
obs=m.get('obsidian') or {}; grd=m.get('guardians') or {}; gov=m.get('government') or {}
print(f"WORLD      : {M}Obsidian treasury=${obs.get('treasury','?')} ops={obs.get('operations','?')} heat={obs.get('heat','?')}{X} | {B}Guardians recovered=${grd.get('assets_recovered','?')} contained={grd.get('incidents_contained','?')}{X} | {Y}cases={gov.get('open_cases','?')}{X}")
alerts=len(f.get('active_alerts') or [])
fc=Y if alerts else G
print(f"FINANCE    : {G}citizen deposits=${f.get('total_citizen_deposits','?')} | accounts={f.get('account_count','?')}{X} | {fc}alerts={alerts}{X}")
print(f"ECONOMY    : {C}week={e.get('world_week','?')}{X} | {G}spending=${e.get('consumer_spending_week','?')} | taxes=${e.get('tax_revenue_week','?')} | settled HH={e.get('settled_households','?')}{X}")
hh_l=h.get('households','?'); hh_e=e.get('households','?')
print(f"LIFECYCLE  : {C}population={h.get('population','?')} | households={hh_l} | babies={(h.get('life_stages') or {}).get('baby',0)} | children={(h.get('life_stages') or {}).get('child',0)+(h.get('life_stages') or {}).get('early_childhood',0)}{X}")
if isinstance(hh_l,(int,float)) and isinstance(hh_e,(int,float)) and hh_l != hh_e:
    print(f"ARCH WARN  : {Y}household truth is split: lifecycle={hh_l} vs economy={hh_e} -- integration pending{X}")
PY
}

while true; do audit_once; sleep 15; done &
STATUS_PID=$!

FILES=()
for f in \
  "$APP/logs/detroit-persistent-launchd-error.log" \
  "$APP/logs/live-world-persistent.log" \
  "$WORLD/mission_justice/events.ndjson" \
  "$WORLD/finance/ledger.ndjson" \
  "$WORLD/human_economy/events.ndjson" \
  "$WORLD/humanity/lifecycle_events.ndjson" \
  "$WORLD/mobility/events.ndjson"; do
  [ -f "$f" ] && FILES+=("$f")
done

if [ "${#FILES[@]}" -eq 0 ]; then
  printf '%sNo recorder streams exist yet; status monitor will continue.%s\n' "$YELLOW" "$RESET"
  wait "$STATUS_PID"
else
  printf '\n%s----- RAW STREAMS -----%s\n' "$CYAN" "$RESET"
  tail -n 8 -F "${FILES[@]}" | awk '
  BEGIN {
    reset="\033[0m"; red="\033[1;31m"; green="\033[1;32m"; yellow="\033[1;33m";
    blue="\033[1;34m"; magenta="\033[1;35m"; cyan="\033[1;36m"; dim="\033[2m";
  }
  {
    line=$0; color="";
    if (line ~ /^==> .* <==$/) color=dim;
    else if (line ~ /Failed to parse reflection|REPETITIVE_GENERATION|truncated|WARNING|WARN|retry|Retry|stale/) color=yellow;
    else if (line ~ /UnboundLocalError|Traceback|CRITICAL|FATAL|ERROR|Exception|exception|OFFLINE|STOPPED|MISSING|deadlock|timed out|timeout/) color=red;
    else if (line ~ /TGOT|Guardian|GUARDIAN|thai_guardians/) color=blue;
    else if (line ~ /Morbeious|Obsidian|OBSIDIAN|criminal_operation|case_opened|CASE-|crime|Crime/) color=magenta;
    else if (line ~ /completed|ONLINE|HEALTHY|PASS|posted|week_settled|synchronized|success|recovered/) color=green;
    else if (line ~ /== .* STAGE ==|mission_cycle_started|ACTIVITY|world_week|mobility_week_generated/) color=cyan;
    if (color != "") print color line reset; else print line;
    fflush();
  }'
fi
