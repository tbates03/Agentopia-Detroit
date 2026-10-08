#!/bin/bash
set -eu

APP="${AGENTOPIA_LIVE:-$HOME/AI/Agentopia}"
LABEL="com.agentopia.detroit.persistent"
GUI_DOMAIN="gui/$(id -u)"
USER_DOMAIN="user/$(id -u)"
DOMAIN="$GUI_DOMAIN"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$APP/logs"
BACKUPDIR="$APP/backups/launchd/$(date +%Y%m%d-%H%M%S)"
PY="$APP/.venv/bin/python"

[ -d "$APP" ] || { echo "ERROR: live Agentopia not found: $APP"; exit 10; }
[ -x "$PY" ] || PY="$(command -v python3 2>/dev/null || true)"
[ -n "$PY" ] || { echo "ERROR: python3 not found"; exit 11; }
[ -x "$APP/scripts/start_detroit_persistent_service.sh" ] || chmod +x "$APP/scripts/start_detroit_persistent_service.sh"

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR" "$BACKUPDIR"

echo "======================================================"
echo " AGENTOPIA DETROIT LAUNCHD REPAIR"
echo "======================================================"
echo "Live root: $APP"
echo "Label:     $LABEL"
echo "GUI domain:  $GUI_DOMAIN"
echo "User domain: $USER_DOMAIN"
echo "Plist:     $PLIST"
echo ""

if [ -f "$PLIST" ]; then
  cp -p "$PLIST" "$BACKUPDIR/$LABEL.plist.before"
  echo "Backed up existing plist to:"
  echo "  $BACKUPDIR/$LABEL.plist.before"
fi

TMP="$PLIST.tmp.$$"
export AGENTOPIA_PLIST_OUT="$TMP"
export AGENTOPIA_LIVE_ROOT="$APP"
export AGENTOPIA_LABEL="$LABEL"

"$PY" <<'PY'
import os, plistlib
from pathlib import Path

out = Path(os.environ["AGENTOPIA_PLIST_OUT"])
app = Path(os.environ["AGENTOPIA_LIVE_ROOT"])
label = os.environ["AGENTOPIA_LABEL"]

payload = {
    "Label": label,
    "ProgramArguments": [
        "/bin/bash",
        str(app / "scripts" / "start_detroit_persistent_service.sh"),
    ],
    "WorkingDirectory": str(app),
    "EnvironmentVariables": {
        "AGENTOPIA_HOME": str(app),
        "AGENTOPIA_LIVE": str(app),
        "PYTHONUNBUFFERED": "1",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    },
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "ThrottleInterval": 15,
    "StandardOutPath": str(app / "logs" / "agentopia-launchd.out.log"),
    "StandardErrorPath": str(app / "logs" / "agentopia-launchd.err.log"),
}
with out.open("wb") as f:
    plistlib.dump(payload, f, sort_keys=False)
PY

/usr/bin/plutil -lint "$TMP"
chmod 644 "$TMP"
mv "$TMP" "$PLIST"
chmod 644 "$PLIST"
xattr -d com.apple.quarantine "$PLIST" >/dev/null 2>&1 || true

echo ""
echo "Normalizing ownership and permissions..."
chown "$(id -u):$(id -g)" "$PLIST" 2>/dev/null || true
chmod 644 "$PLIST"
chmod 755 "$HOME/Library/LaunchAgents" 2>/dev/null || true

echo ""
echo "Current disabled-state hints:"
launchctl print-disabled "$GUI_DOMAIN" 2>/dev/null | grep "$LABEL" || true
launchctl print-disabled "$USER_DOMAIN" 2>/dev/null | grep "$LABEL" || true

echo ""
echo "Stopping stale registrations in both domains..."
launchctl bootout "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootout "$USER_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootout "$GUI_DOMAIN" "$PLIST" >/dev/null 2>&1 || true
launchctl bootout "$USER_DOMAIN" "$PLIST" >/dev/null 2>&1 || true
launchctl remove "$LABEL" >/dev/null 2>&1 || true
sleep 1

echo "Explicitly enabling the label..."
launchctl enable "$GUI_DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl enable "$USER_DOMAIN/$LABEL" >/dev/null 2>&1 || true

bootstrap_domain() {
  CANDIDATE="$1"
  echo ""
  echo "Trying launchctl bootstrap in $CANDIDATE ..."
  OUT="$(launchctl bootstrap "$CANDIDATE" "$PLIST" 2>&1)" && {
    DOMAIN="$CANDIDATE"
    echo "Bootstrap accepted in $DOMAIN."
    return 0
  }
  RC=$?
  echo "$OUT"
  echo "bootstrap exit: $RC"
  return "$RC"
}

if ! bootstrap_domain "$GUI_DOMAIN"; then
  echo ""
  echo "GUI-domain bootstrap failed. Capturing launchd diagnostics..."
  echo "--- plist metadata ---"
  ls -ldeO@ "$HOME/Library/LaunchAgents" "$PLIST" 2>/dev/null || true
  echo "--- launchctl gui-domain state ---"
  launchctl print "$GUI_DOMAIN" 2>/dev/null | sed -n '1,160p' || true
  echo "--- launchd recent log ---"
  /usr/bin/log show --last 5m --style compact --predicate 'process == "launchd"' 2>/dev/null | tail -n 160 || true

  echo ""
  echo "Trying user-domain fallback for this headless background service..."
  if ! bootstrap_domain "$USER_DOMAIN"; then
    echo ""
    echo "ERROR: launchctl bootstrap failed in both GUI and user domains."
    echo "Current plist:"
    /usr/bin/plutil -p "$PLIST" || true
    echo ""
    echo "macOS may have disabled this background item in System Settings > General > Login Items & Extensions."
    exit 20
  fi
fi

echo "$DOMAIN" > "$APP/runtime/launchd_domain"

echo "Kickstarting $LABEL in $DOMAIN..."
KICK_OUT="$(launchctl kickstart "$DOMAIN/$LABEL" 2>&1)" || {
  RC=$?
  echo "$KICK_OUT"
  echo "ERROR: launchctl kickstart failed (exit $RC)"
  /usr/bin/log show --last 5m --style compact --predicate 'process == "launchd"' 2>/dev/null | tail -n 120 || true
  exit 21
}

sleep 3

echo ""
echo "=== LAUNCHD OWNERSHIP ==="
launchctl print "$DOMAIN/$LABEL" | sed -n '1,120p'

if ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "ERROR: launchd does not own $LABEL after repair."
  exit 22
fi

echo ""
echo "=== PROCESS CHECK ==="
PIDS="$(pgrep -f '[s]cripts/start_detroit_persistent_service.sh|[r]un_detroit_persistent.py' 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  ps -o pid=,ppid=,etime=,command= -p "$(printf '%s' "$PIDS" | paste -sd, -)"
else
  echo "No matching process yet; launchd may still be starting models."
fi

echo ""
echo "=== SERVICE HEALTH ==="
for i in $(seq 1 60); do
  OBS=0; ENG=0
  curl -fsS --max-time 1 http://127.0.0.1:8766/api/health >/dev/null 2>&1 && OBS=1
  pgrep -f '[r]un_detroit_persistent.py' >/dev/null 2>&1 && ENG=1
  if [ "$OBS" -eq 1 ] && [ "$ENG" -eq 1 ]; then
    echo "Observer: READY"
    echo "Engine:   RUNNING"
    echo "launchd:  SUPERVISING"
    echo ""
    echo "Launchd repair PASS."
    exit 0
  fi
  sleep 2
done

echo "Observer or engine did not become ready within the verification window."
echo ""
echo "=== STDOUT TAIL ==="
tail -n 80 "$LOGDIR/agentopia-launchd.out.log" 2>/dev/null || true
echo ""
echo "=== STDERR TAIL ==="
tail -n 80 "$LOGDIR/agentopia-launchd.err.log" 2>/dev/null || true
echo ""
echo "=== LIVE WORLD TAIL ==="
tail -n 80 "$LOGDIR/live-world-persistent.log" 2>/dev/null || true
exit 23
