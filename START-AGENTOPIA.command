#!/bin/bash

APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
cd "$APP" || exit 1

clear

echo ""
echo "======================================================"
echo "                AGENTOPIA"
echo "             AI SOCIETY START"
echo "======================================================"
echo ""

# ------------------------------------------------------
# Python environment
# ------------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "ERROR: Agentopia Python environment is missing."
    echo ""
    echo "Expected:"
    echo "$APP/.venv"
    echo ""
    read -p "Press ENTER to close..."
    exit 1
fi

# ------------------------------------------------------
# Start Ollama if necessary
# ------------------------------------------------------
if open -Ra "Ollama" >/dev/null 2>&1; then
    open -a "Ollama" >/dev/null 2>&1 || true
fi

for i in 1 2 3 4 5 6 7 8; do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "ERROR: Ollama is not responding."
    echo ""
    echo "Start Ollama and try again."
    echo ""
    read -p "Press ENTER to close..."
    exit 1
fi

# ------------------------------------------------------
# Validate actual selected Agentopia models
# ------------------------------------------------------
.venv/bin/python <<'PY'
import json
import sys

with open("config.json", "r", encoding="utf-8") as f:
    c = json.load(f)

models = c.get("models", {})

required = [
    ("role_model", c.get("role_model")),
    ("god_model", c.get("god_model")),
    ("fallback_model", c.get("fallback_model"))
]

for field, model in required:
    if not model:
        print(f"ERROR: {field} is not configured.")
        sys.exit(1)

    if model not in models:
        print(f"ERROR: {field} points to missing model '{model}'.")
        sys.exit(1)

print("Configuration: OK")
print()
print("Citizen model: ", c["role_model"])
print("World model:   ", c["god_model"])
print("Fallback:      ", c["fallback_model"])
print("World:         ", c["world"]["name"])
PY

if [ $? -ne 0 ]; then
    echo ""
    read -p "Press ENTER to close..."
    exit 1
fi

echo ""
echo "Ollama: ONLINE"
echo ""
echo "Starting the Agentopia society..."
echo ""
echo "CTRL+C stops the simulation."
echo ""
echo "------------------------------------------------------"
echo ""

source .venv/bin/activate

python scripts/run_world.py --world apartment

echo ""
echo "------------------------------------------------------"
echo "Agentopia simulation stopped."
echo ""

read -p "Press ENTER to close..."
