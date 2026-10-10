#!/usr/bin/env python3
"""Advisory local AI for an isolated City Sandbox; never edits canonical world state."""
import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from run_city_sandbox import stage, read

ACTIONS = {"work", "study", "rest", "socialize", "travel", "volunteer"}

def validate_url(url):
    p = urlsplit(url)
    if p.scheme != "http" or p.hostname not in ("127.0.0.1", "localhost") or p.path != "/v1/chat/completions" or p.username or p.password or p.query or p.fragment or not p.port or not (1024 <= p.port <= 65535):
        raise ValueError("Only localhost OpenAI-compatible chat endpoints are allowed")
    return url

def advice(folder, count=4, endpoint="http://127.0.0.1:8081/v1/chat/completions", model="agentopia-citizen", dry_run=True, client=None):
    validate_url(endpoint)
    folder, manifest, _ = stage(folder)
    state = read(folder)
    residents = state["residents"]
    if not (1 <= count <= 8) or not residents:
        raise ValueError("Require 1-8 selected agents and nonempty resident state")
    offset = (state["tick"] * count) % len(residents)
    cohort = [residents[(offset+i) % len(residents)] for i in range(min(count, len(residents)))]
    identity = json.dumps([state["world_id"], state["tick"], model, [p["id"] for p in cohort]])
    decision_id = hashlib.sha256(identity.encode()).hexdigest()
    path = folder / "city_ai" / "decisions.json"
    if not dry_run and path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("decision_id") == decision_id:
            return old
    decisions = []
    for resident in cohort:
        action, source = "rest", "fallback"
        if not dry_run:
            try:
                messages = [
                    {"role": "system", "content": "Fictional city resident activity adviser. Respond only as JSON: {\"action\":\"work\"}. Allowed actions: work, study, rest, socialize, travel, volunteer. No tools."},
                    {"role": "user", "content": json.dumps({"city":state["world_id"], "time":state["time"], "resident_id":resident["id"], "job":resident["job"], "previous_activity":resident["activity"]})}
                ]
                payload = {"model":model,"messages":messages,"temperature":0,"max_tokens":64}
                if client is None:
                    req = urllib.request.Request(endpoint, json.dumps(payload).encode(), {"Content-Type":"application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=8) as response:
                        raw = response.read(32769)
                    if len(raw) > 32768:
                        raise ValueError("Oversized local model response")
                    response = json.loads(raw)
                else:
                    response = client(payload)
                choice = json.loads(response["choices"][0]["message"]["content"])["action"]
                if choice not in ACTIONS:
                    raise ValueError("Disallowed activity")
                action, source = choice, "local-model"
            except (Exception):
                pass  # Fail closed to bounded deterministic fallback
        decisions.append({"resident_id":resident["id"],"proposed_action":action,"source":source})
    result = {"schema":"agentopia.city.ai.advice.v1","world_id":state["world_id"],"sandbox_tick":state["tick"],"decision_id":decision_id,"advisory_only":True,"decisions":decisions}
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent,prefix=".city-ai-")
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump(result,f,indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return result

def main():
    ap = argparse.ArgumentParser(description="Isolated City Sandbox optional local AI adviser")
    ap.add_argument("world",type=Path)
    ap.add_argument("--agents",type=int,default=4)
    ap.add_argument("--endpoint",default="http://127.0.0.1:8081/v1/chat/completions")
    ap.add_argument("--model",default="agentopia-citizen")
    ap.add_argument("--live",action="store_true",help="Call local model and write advisory decisions only")
    args=ap.parse_args()
    print(json.dumps(advice(args.world,args.agents,args.endpoint,args.model,not args.live),indent=2))

if __name__ == "__main__":
    main()
