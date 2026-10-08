#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
HEARTBEAT = RUNTIME / "world_context_heartbeat.json"

import sys
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import detroit_world_context as ctx

running = True


def stop(*_args):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)


def write_heartbeat(summary):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "pid": os.getpid(),
        "unix": time.time(),
        "version": ctx.VERSION,
        "engine_time": summary.get("engine_time"),
        "season": summary.get("season", {}).get("name"),
        "weather": summary.get("weather", {}).get("condition"),
    }, indent=2) + "\n", encoding="utf-8")
    tmp.replace(HEARTBEAT)


last_key = None
while running:
    try:
        clock = ctx.observed_clock()
        key = (clock.get("raw"), clock.get("day"))
        summary = ctx.refresh(clock, append_event=(key != last_key))
        last_key = key
        write_heartbeat(summary)
    except Exception:
        pass
    time.sleep(5)
