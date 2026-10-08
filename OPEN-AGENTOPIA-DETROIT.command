#!/bin/bash
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
PLIST="$HOME/Library/LaunchAgents/com.agentopia.detroit.persistent.plist"
if command -v launchctl >/dev/null 2>&1 && [ -f "$PLIST" ]; then
  DOMAIN="gui/$(id -u)"
  launchctl bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
  launchctl kickstart "$DOMAIN/com.agentopia.detroit.persistent" >/dev/null 2>&1 || true
else
  nohup "$APP/scripts/start_detroit_persistent_service.sh" >> "$APP/logs/detroit-manual-start.log" 2>&1 &
fi
sleep 1
# AGENTOPIA_FLIGHT_RECORDER_V17451
"$APP/scripts/open_agentopia_flight_recorder_console.sh" >/dev/null 2>&1 || true
command -v open >/dev/null 2>&1 && open "http://127.0.0.1:8766" || true
