#!/bin/bash
set -e

APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
LIVE="${AGENTOPIA_LIVE:-$HOME/AI/Agentopia}"
PY="$APP/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 2>/dev/null || true)"

if [ -z "$PY" ]; then
  echo "ERROR: python3 not found."
  read -p "Press ENTER to close..."
  exit 1
fi

clear
echo "======================================================"
echo " AGENTOPIA DETROIT RC2 POST-REBOOT HARDENING"
echo "======================================================"
echo ""
echo "Public source: $APP"
echo "Live root:     $LIVE"
echo ""
echo "This applies the post-reboot RC2 fixes:"
echo "  - early/current engine heartbeat"
echo "  - lifecycle/economy household truth reconciliation"
echo "  - lifecycle -> SQLite synchronization"
echo "  - clean Live World client disconnect handling"
echo "  - stricter RC2 heartbeat/system validation"
echo ""
echo "A full live-world/code backup is created before changes."
echo ""

"$PY" "$APP/scripts/apply_rc2_post_reboot_hardening.py"   --public "$APP"   --live "$LIVE"
RC=$?

echo ""
if [ "$RC" -eq 0 ]; then
  echo "RC2 post-reboot hardening completed successfully."
else
  echo "RC2 post-reboot hardening failed; rollback was attempted."
fi
echo ""
read -p "Press ENTER to close..."
exit "$RC"
