#!/usr/bin/env python3
"""Isolated synthetic city sandbox. Does not import or launch Detroit engine."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from import_city_manifest import validate_manifest, sha256_json

STAGES = ("morning", "work", "afternoon", "evening")
JOBS = ("teacher", "health worker", "engineer", "cook", "transit worker", "artist", "student", "shopkeeper")
ID_PATTERN = re.compile(r"^city_[a-z0-9][a-z0-9-]{1,48}$")


def stage(folder):
    folder = Path(folder).expanduser().resolve()
    if not ID_PATTERN.fullmatch(folder.name) or folder.name in ("city_detroit", "city_detroit-persistent"):
        raise ValueError("Expected independent city_<id> directory (Detroit reserved)")
    if not (folder / "DO_NOT_LAUNCH.txt").is_file():
        raise ValueError("Missing City Builder staging marker")
    manifest = validate_manifest(json.loads((folder / "manifest.json").read_text(encoding="utf-8")))
    report = json.loads((folder / "import_report.json").read_text(encoding="utf-8"))
    geo = json.loads((folder / "geography.json").read_text(encoding="utf-8"))
    if manifest["world_id"] != folder.name[5:] or sha256_json(manifest) != report.get("manifest_sha256"):
        raise ValueError("Manifest or directory identity mismatch")
    if geo.get("schema") != "agentopia.city.geography.v1" or geo.get("world_id") != manifest["world_id"]:
        raise ValueError("Geography identity mismatch")
    return folder, manifest, geo


def choose(items, *parts):
    key = "|".join(map(str, parts))
    return items[int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) % len(items)]


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".city-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def state_path(folder):
    return folder / "sandbox_runtime" / "state.json"


def initialize(folder, population=32):
    folder, manifest, geo = stage(folder)
    if not (1 <= population <= 250):
        raise ValueError("Population must be 1-250")
    if state_path(folder).exists():
        raise FileExistsError("World already initialized; no overwrite")
    areas = [x["name"] for x in geo.get("neighborhoods", [])] or ["City Center"]
    places = [x["name"] for x in geo.get("places", [])] or ["Civic Center"]
    people = []
    for n in range(1, population + 1):
        rid = f'{manifest["world_id"]}-resident-{n:05d}'
        home = choose(areas, rid, "home")
        people.append({"id": rid, "name": f"Resident {n:03d}",
                       "job": choose(JOBS, rid, "job"), "home": home,
                       "workplace": choose(places, rid, "work"),
                       "location": home, "activity": "home"})
    state = {"schema": "agentopia.city.sandbox.state.v1", "world_id": manifest["world_id"],
             "simulator": "deterministic-sandbox-no-llm", "tick": 0,
             "time": {"year": 2045, "week": 1, "day": 1, "stage": "pending"},
             "residents": people, "recent_events": [], "created_at": datetime.now(timezone.utc).isoformat()}
    write_atomic(state_path(folder), state)
    return state


def read(folder):
    folder, manifest, _ = stage(folder)
    state = json.loads(state_path(folder).read_text(encoding="utf-8"))
    if state.get("schema") != "agentopia.city.sandbox.state.v1" or state.get("world_id") != manifest["world_id"]:
        raise ValueError("Invalid resident state / world mismatch")
    return state


def clock(tick):
    days, phase = divmod(tick - 1, 4)
    years, week = divmod(days // 7, 52)
    return {"year": 2045 + years, "week": week + 1, "day": (days % 7) + 1, "stage": STAGES[phase]}


def advance(folder, count=1):
    if not (1 <= count <= 10000):
        raise ValueError("Steps must be between 1 and 10000")
    folder, manifest, geo = stage(folder)
    state = read(folder)
    places = [x["name"] for x in geo.get("places", [])] or ["Civic Center"]
    for _ in range(count):
        tick = state["tick"] + 1
        sim_time = clock(tick)
        events = []
        for p in state["residents"]:
            phase = sim_time["stage"]
            if phase == "morning":
                activity, location = "commute", p["workplace"]
            elif phase == "work":
                activity, location = ("study" if p["job"] == "student" else "work"), p["workplace"]
            elif phase == "afternoon":
                activity, location = "community", choose(places, p["id"], tick)
            else:
                activity, location = "rest", p["home"]
            p["activity"], p["location"] = activity, location
            events.append({"id": f'{manifest["world_id"]}:{tick}:{p["id"]}',
                           "tick": tick, "resident_id": p["id"],
                           "activity": activity, "location": location})
        state["tick"], state["time"] = tick, sim_time
        state["recent_events"] = (state["recent_events"] + events)[-250:]
    write_atomic(state_path(folder), state)
    return state


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agentopia City Sandbox</title><style>
body{font:16px system-ui;background:#101b30;color:#e7f1ff;max-width:1050px;margin:auto;padding:24px}
section{border:1px solid #435672;border-radius:12px;padding:18px;margin:16px 0}table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:9px;border-bottom:1px solid #36465c}small{color:#a9c6e2}
</style></head><body><h1 id="city">City Sandbox</h1><small>Separate synthetic activity runtime; not the full Agentopia AI engine.</small>
<section><h2 id="clock">Loading</h2><p id="pop"></p></section><section><h2>Residents</h2>
<table><thead><tr><th>Citizen</th><th>Profession</th><th>Activity</th><th>Location</th></tr></thead><tbody id="rows"></tbody></table></section>
<script>
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function refresh(){try{let r=await fetch('/api/snapshot',{cache:'no-store'});if(!r.ok)throw Error(r.status);let s=await r.json();
document.querySelector('#city').textContent=s.world_id;
document.querySelector('#clock').textContent='Y'+s.time.year+' W'+s.time.week+' D'+s.time.day+' '+s.time.stage;
document.querySelector('#pop').textContent=s.residents.length+' synthetic residents · tick '+s.tick;
document.querySelector('#rows').innerHTML=s.residents.map(p=>'<tr>'+[p.name,p.job,p.activity,p.location].map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('');
}catch(e){document.querySelector('#clock').textContent='Offline: '+e.message}}
refresh();setInterval(refresh,3000);
</script></body></html>"""


def serve(folder, port, interval=0):
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be 1024-65535")
    lock = threading.RLock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/health", "/api/snapshot"):
                self.send_error(404)
                return
            with lock:
                current = read(folder)
            if self.path == "/":
                payload, mime = PAGE.encode(), "text/html; charset=utf-8"
            else:
                info = current if self.path == "/api/snapshot" else {"ok": True, "world_id": current["world_id"], "tick": current["tick"]}
                payload, mime = json.dumps(info).encode(), "application/json"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
    if interval and not 1 <= interval <= 3600:
        raise ValueError("Interval must be 1-3600 seconds")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if interval:
        def tick_loop():
            while True:
                time.sleep(interval)
                with lock:
                    advance(folder)
        threading.Thread(target=tick_loop, daemon=True).start()
    print(f"City viewer http://127.0.0.1:{port} | auto tick={interval}", flush=True)
    server.serve_forever()


def main():
    ap = argparse.ArgumentParser(description="Independent city sandbox; does not start Detroit's engine")
    ap.add_argument("command", choices=("init", "step", "status", "serve", "run"))
    ap.add_argument("folder", type=Path)
    ap.add_argument("--population", type=int, default=32)
    ap.add_argument("--steps", type=int, default=1)
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--interval", type=int, default=3)
    a = ap.parse_args()
    try:
        if a.command == "init":
            result = initialize(a.folder, a.population)
        elif a.command == "step":
            result = advance(a.folder, a.steps)
        elif a.command == "status":
            result = read(a.folder)
        else:
            read(a.folder)
            serve(a.folder, a.port, a.interval if a.command == "run" else 0)
            return
        print(json.dumps({"ok": True, "world_id": result["world_id"], "tick": result["tick"],
                          "population": len(result["residents"]), "time": result["time"]}, indent=2))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        ap.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
