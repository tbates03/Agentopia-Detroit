#!/bin/bash
APP="${AGENTOPIA_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
"$PY" - "$APP" <<'PY'
import json, subprocess, sys, urllib.request
from pathlib import Path
app=Path(sys.argv[1]); w=app/'data'/'detroit_persistent'
def j(p,d={}):
    try:return json.loads(p.read_text())
    except:return d
def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=.8) as r:return r.status==200
    except:return False
print('AGENTOPIA DETROIT')
print('Mode: PERSISTENT WORLD')
print('World:', w)
print('Checkpoint:', j(w/'checkpoint.json',{}))
meta=j(w/'persistent_world.json',{})
print('Boot count:', meta.get('boot_count',0))
print('llama.cpp citizen :8081:', 'READY' if health(8081) else 'OFFLINE')
print('llama.cpp strategy :8082:', 'READY' if health(8082) else 'OFFLINE')
print('llama.cpp cyber    :8083:', 'READY' if health(8083) else 'OPTIONAL/OFFLINE')
bf=app/'runtime'/'llama'/'active_backend'
print('Active backend:', bf.read_text().strip() if bf.exists() else 'unknown')
pop=len([p for p in (w/'persona').iterdir() if p.is_dir()]) if (w/'persona').exists() else 0
active=len([p for p in (w/'persona').iterdir() if p.is_dir() and not (p/'_background.json').exists()]) if (w/'persona').exists() else 0
print('Population:',pop,'| active AI:',active)
print('World process:', 'RUNNING' if subprocess.run(['pgrep','-f','[Pp]ython.*scripts/run_world.py'],stdout=subprocess.DEVNULL).returncode==0 else 'STOPPED')
dt=j(w/'digital_twin'/'state.json',{})
print('Digital twin:', 'READY' if (w/'digital_twin'/'state.json').exists() else 'OFFLINE', '| campaigns',dt.get('campaigns',0),'| resilience',dt.get('resilience','?'))
print('Dashboard: http://127.0.0.1:8766')
PY
read -p "Press ENTER to close..."
