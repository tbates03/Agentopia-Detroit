#!/bin/bash
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
"$PY" "$APP/scripts/detroit_human_economy.py" status
