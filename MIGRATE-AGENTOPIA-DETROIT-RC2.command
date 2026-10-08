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
echo " AGENTOPIA DETROIT v1.8.0-RC2 GUARDED LIVE MIGRATION"
echo "======================================================"
echo ""
echo "Public source: $APP"
echo "Live world:    $LIVE"
echo ""
echo "This will:"
echo "  1) update the public RC2 repo"
echo "  2) pause live Detroit"
echo "  3) back up the entire persistent world and replaced code"
echo "  4) sync RC2 code without overwriting persistent data"
echo "  5) build civilization.sqlite3"
echo "  6) run invariants + growth audit + 100K stress test"
echo "  7) verify checkpoint/population counts are unchanged"
echo "  8) restart Detroit and verify observer + engine + active cohort"
echo ""
echo "Any failed gate leaves Detroit paused for inspection."
echo ""

"$PY" "$APP/scripts/migrate_detroit_rc2.py" --public "$APP" --live "$LIVE"
RC=$?

echo ""
if [ "$RC" -eq 0 ]; then
  echo "RC2 migration completed successfully."
else
  echo "RC2 migration did NOT complete. Detroit was left paused."
  echo "Review the migration output and backup path above."
fi
echo ""
read -p "Press ENTER to close..."
exit "$RC"
