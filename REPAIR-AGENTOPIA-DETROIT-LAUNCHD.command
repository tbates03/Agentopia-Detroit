#!/bin/bash
set -e
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
LIVE="${AGENTOPIA_LIVE:-$HOME/AI/Agentopia}"

clear
echo "======================================================"
echo " AGENTOPIA DETROIT - REPAIR PERSISTENCE"
echo "======================================================"
echo ""
echo "Public source: $APP"
echo "Live root:     $LIVE"
echo ""
echo "This repairs the macOS launchd registration and verifies"
echo "that launchd is supervising Detroit instead of the manual fallback."
echo ""

AGENTOPIA_LIVE="$LIVE" "$APP/scripts/repair_detroit_launchd.sh"
RC=$?

echo ""
if [ "$RC" -eq 0 ]; then
  echo "Persistent launchd service repair completed successfully."
else
  echo "Launchd repair failed. Review the diagnostics above."
fi
echo ""
read -p "Press ENTER to close..."
exit "$RC"
