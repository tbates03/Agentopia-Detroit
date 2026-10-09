#!/bin/bash
set -euo pipefail
APP="${AGENTOPIA_HOME:-$HOME/AI/Agentopia}"
WORLD="$APP/data/detroit_persistent"
VERSION="1.7.4.5.1"
PY="$APP/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
PENDING="$APP/runtime/pending-v17451.json"
RUNNER="$APP/scripts/run_detroit_persistent.py"
SERVER="$APP/live_world/server.py"
INDEX="$APP/live_world/static/index.html"
APPJS="$APP/live_world/static/app.js"
CHECKER="$APP/AGENTOPIA-FULL-SYSTEM-CHECK.command"
if pgrep -f '[r]un_detroit_persistent.py' >/dev/null 2>&1; then
  echo "ERROR: v$VERSION activation refused because the persistent engine is running." >&2
  exit 9
fi
[ -f "$PENDING" ] || exit 0
printf '%s\n' "$VERSION" > "$APP/VERSION"
"$PY" - "$APP" "$WORLD" "$RUNNER" "$SERVER" "$INDEX" "$APPJS" "$CHECKER" "$VERSION" <<'PY'
from pathlib import Path
import json,re,sys
from datetime import datetime,timezone
app,world=Path(sys.argv[1]),Path(sys.argv[2]); runner,server,index,appjs,checker=map(Path,sys.argv[3:8]); version=sys.argv[8]; now=datetime.now(timezone.utc).isoformat()
for rp in (app/'runtime'/'release.json',world/'release.json'):
    try:d=json.loads(rp.read_text()) if rp.exists() else {}
    except:d={}
    if not isinstance(d,dict):d={}
    d.update({'version':version,'release':f'Agentopia Detroit v{version}','name':'Observability + UI Stability','updated_at':now})
    rp.parent.mkdir(parents=True,exist_ok=True); rp.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
if runner.exists():
    s=runner.read_text(); s,n=re.subn(r'(?m)^VERSION\s*=\s*["\'][^"\']+["\']',f'VERSION = "{version}"',s,count=1)
    if not n: raise SystemExit('runner VERSION assignment missing')
    runner.write_text(s)
if server.exists():
    s=server.read_text(); s=re.sub(r'server_version\s*=\s*"AgentopiaDetroit/[^"]+"',f'server_version = "AgentopiaDetroit/{version}-observability-stability"',s,count=1)
    s=re.sub(r'"app_version"\s*:\s*"[^"]+"',f'"app_version": "{version}"',s); s=re.sub(r'"release_version"\s*:\s*"[^"]+"',f'"release_version": "{version}"',s); server.write_text(s)
for fp in (index,appjs):
    if fp.exists():
        s=fp.read_text(); s=re.sub(r'Agentopia Detroit v1(?:\.\d+){2,4}',f'Agentopia Detroit v{version}',s); fp.write_text(s)
if checker.exists():
    s=checker.read_text(); s=re.sub(r'Agentopia Detroit v1(?:\.\d+){2,4}',f'Agentopia Detroit v{version}',s)
    s=re.sub(r'(?m)^(\s*(?:EXPECTED_VERSION|VERSION_EXPECTED|EXPECTED)\s*=\s*)["\'][^"\']+["\']',lambda m:m.group(1)+f'"{version}"',s)
    checker.write_text(s)
PY
"$PY" -m py_compile "$APP/src/world/god.py" "$RUNNER" "$SERVER"
rm -f "$PENDING"
echo "ACTIVATED: Agentopia Detroit v$VERSION"
