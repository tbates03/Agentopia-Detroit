#!/bin/bash

cd "$(dirname "$0")" || exit 1

echo ""
echo "Updating Agentopia..."
echo ""

git pull --ff-only

source .venv/bin/activate
python -m pip install -r requirements.txt

echo ""
echo "Update complete."
echo ""

read -p "Press ENTER to close..."
