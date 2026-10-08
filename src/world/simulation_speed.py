from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PRESETS = {
    "slow": {"label":"Slow", "multiplier":0.5, "timeline_multiplier":0.5, "concurrency_factor":0.5},
    "normal": {"label":"Normal", "multiplier":1, "timeline_multiplier":1, "concurrency_factor":1},
    "x2": {"label":"Fast x2", "multiplier":2, "timeline_multiplier":2, "concurrency_factor":2},
    "x5": {"label":"Faster x5", "multiplier":5, "timeline_multiplier":5, "concurrency_factor":4},
    "x10": {"label":"Fastest x10", "multiplier":10, "timeline_multiplier":10, "concurrency_factor":6},
    "x1000": {"label":"Ludicrous x1000", "multiplier":1000, "timeline_multiplier":1000, "concurrency_factor":6},
}


def speed_file() -> Path:
    return Path("data") / "simulation_speed.json"


def read_speed() -> dict[str, Any]:
    try:
        data = json.loads(speed_file().read_text(encoding="utf-8"))
    except Exception:
        data = {"mode":"normal"}
    mode = str(data.get("mode") or "normal")
    preset = PRESETS.get(mode, PRESETS["normal"])
    return {"mode":mode if mode in PRESETS else "normal", **preset}


def apply_speed_profile(world: Any) -> dict[str, Any]:
    state = read_speed()
    base = int(
        getattr(world, "_detroit_base_concurrency", 0)
        or getattr(world, "max_concurrency", 2)
        or 2
    )
    if not hasattr(world, "_detroit_base_concurrency"):
        world._detroit_base_concurrency = base

    # AGENTOPIA_ADAPTIVE_CONCURRENCY_V180
    # Original Detroit speed control hard-capped every fast mode at 12 workers,
    # so x1000 could not use more local inference capacity than Normal. Keep
    # Normal conservative while letting faster modes scale to a configurable cap.
    try:
        requested_cap = int(os.environ.get("AGENTOPIA_CONCURRENCY_CAP", "32"))
    except Exception:
        requested_cap = 32
    cap = max(1, min(base, requested_cap))

    mode = state["mode"]
    if mode == "slow":
        target = 1
    elif mode == "normal":
        target = min(cap, 12)
    elif mode == "x2":
        target = min(cap, 16)
    elif mode == "x5":
        target = min(cap, 24)
    else:  # x10 and x1000
        target = cap

    world.max_concurrency = max(1, target)
    try:
        from src.config import get_config
        get_config()["max_concurrency"] = world.max_concurrency
    except Exception:
        pass
    state["configured_concurrency"] = base
    state["concurrency_cap"] = cap
    state["effective_concurrency"] = world.max_concurrency
    return state
