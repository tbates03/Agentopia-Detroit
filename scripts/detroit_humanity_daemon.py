#!/usr/bin/env python3
from __future__ import annotations
import hashlib, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/"data"/"detroit_persistent"
SCRIPT=ROOT/"scripts"/"detroit_human_lifecycle.py"
PID=ROOT/"runtime"/"detroit-humanity.pid"
PID.parent.mkdir(parents=True,exist_ok=True); PID.write_text(str(__import__('os').getpid()))

def sig():
    parts=[]
    for p in (WORLD/"checkpoint.json",WORLD/"factions.json",WORLD/"cognition"/"summary.json"):
        try:
            st=p.stat(); parts.append(f"{p}:{st.st_mtime_ns}:{st.st_size}")
        except OSError: parts.append(f"{p}:0:0")
    newest=0
    pr=WORLD/"persona"
    if pr.exists():
        for p in pr.rglob("year=*.json"):
            try: newest=max(newest,p.stat().st_mtime_ns)
            except OSError: pass
    parts.append(str(newest))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
last=None
try:
    while True:
        k=sig()
        if k!=last:
            subprocess.run([sys.executable,str(SCRIPT),"update"],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            # Keep the RC2 civilization index synchronized with births, migration,
            # household reconciliation and lifecycle population changes.
            try:
                subprocess.run(
                    [sys.executable,str(ROOT/"scripts"/"detroit_state_store.py"),"sync"],
                    cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False,
                )
            except Exception:
                pass
            last=k
        time.sleep(10)
finally:
    try: PID.unlink()
    except OSError: pass
