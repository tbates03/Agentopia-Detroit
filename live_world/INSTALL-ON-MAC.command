#!/bin/bash
set -euo pipefail
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
DEST="$APP/live_world"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=============================================================="
echo "          INSTALLING AGENTOPIA LIVE WORLD"
echo "=============================================================="
echo ""
if [ ! -d "$APP/data" ]; then
  echo "ERROR: Agentopia was not found at:"
  echo "  $APP"
  exit 1
fi
mkdir -p "$DEST"
rsync -a --delete --exclude '.DS_Store' "$HERE/" "$DEST/"
chmod +x "$DEST/START-LIVE-WORLD.command"
ln -sf "$DEST/START-LIVE-WORLD.command" "$HOME/Desktop/START-AGENTOPIA-LIVE-WORLD.command"

echo "Installed to: $DEST"
echo "Desktop launcher created: START-AGENTOPIA-LIVE-WORLD.command"
echo ""
exec "$DEST/START-LIVE-WORLD.command"
