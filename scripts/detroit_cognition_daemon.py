#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
PID = ROOT / "runtime" / "detroit-cognition.pid"
SCRIPT = ROOT / "scripts" / "detroit_cognitive_society.py"
PID.parent.mkdir(parents=True, exist_ok=True)
PID.write_text(str(os.getpid()), encoding="utf-8")


def signature() -> str:
    paths = [
        WORLD / "checkpoint.json",
        WORLD / "factions.json",
        WORLD / "digital_twin" / "state.json",
        WORLD / "digital_twin" / "cyber_events.jsonl",
        WORLD / "digital_twin" / "audit_events.jsonl",
    ]
    parts = []
    for p in paths:
        try:
            st = p.stat()
            parts.append(f"{p.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{p.name}:0:0")
    # Contacts and profile updates matter too; summarize their newest mtime.
    newest = 0
    persona = WORLD / "persona"
    if persona.exists():
        try:
            for p in persona.rglob("*.jsonl"):
                try: newest = max(newest, p.stat().st_mtime_ns)
                except OSError: pass
            for p in persona.rglob("year=*.json"):
                try: newest = max(newest, p.stat().st_mtime_ns)
                except OSError: pass
        except OSError:
            pass
    parts.append(f"persona:{newest}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()

last = None
try:
    while True:
        key = signature()
        if key != last:
            subprocess.run([sys.executable, str(SCRIPT), "update"], cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            last = key
        time.sleep(5)
finally:
    try: PID.unlink()
    except OSError: pass
