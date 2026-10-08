#!/bin/bash
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
PLIST="$HOME/Library/LaunchAgents/com.agentopia.detroit.persistent.plist"
if command -v launchctl >/dev/null 2>&1 && [ -f "$PLIST" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
fi
for PAT in 'scripts/run_detroit_persistent.py' '[Pp]ython.*scripts/run_world.py.*detroit_persistent' 'scripts/detroit_twin_daemon.py' 'live_world/server.py'; do
  PIDS="$(pgrep -f "$PAT" 2>/dev/null || true)"; [ -z "$PIDS" ] || kill -TERM $PIDS 2>/dev/null || true
done
"$APP/scripts/stop_detroit_llama.sh" || true
echo "Agentopia Detroit paused. Persistent state is unchanged."
read -p "Press ENTER to close..."
