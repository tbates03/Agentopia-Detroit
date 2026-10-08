#!/bin/bash
set -u
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
REC="$APP/scripts/agentopia_flight_recorder.sh"
[ -x "$REC" ] || exit 2
if pgrep -f '[a]gentopia_flight_recorder.sh' >/dev/null 2>&1; then exit 0; fi
/usr/bin/osascript <<OSA >/dev/null 2>&1 || true
tell application "Terminal"
  activate
  do script "bash \"$REC\""
end tell
OSA
