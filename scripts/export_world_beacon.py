#!/usr/bin/env python3
"""Export a privacy-safe, checkpoint-only World Beacon from a local Agentopia world.

The Mac's local checkpoint is authoritative. Public repository submissions are
metadata templates, never substitutes for live progress. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return default


def memory_gb() -> float | None:
    try:
        if sys.platform == "darwin":
            import subprocess
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=3).strip()
            return round(int(raw) / (1024 ** 3), 1)
        info = Path("/proc/meminfo")
        if info.exists():
            for line in info.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 ** 2, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def aggregate_right_sizing(path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {"350M": 0, "1.2B": 0, "2.6B": 0}
    latency_sum = 0.0
    latency_n = success = total = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                tier = str(row.get("tier") or "other")
                counts[tier] = counts.get(tier, 0) + 1
                try:
                    value = float(row.get("latency_ms", 0) or 0)
                    if 0 <= value < 1_000_000:
                        latency_sum += value
                        latency_n += 1
                except (ValueError, TypeError):
                    pass
                success += int(row.get("success") is True)
                total += 1
    except OSError:
        pass
    return {
        "local_inference": True,
        "model_tiers": list(counts),
        "requests_by_tier": counts,
        "success_percent": round(100 * success / total, 1) if total else None,
        "avg_latency_ms": round(latency_sum / latency_n, 1) if latency_n else None,
    }


def valid_checkpoint(world_dir: Path, *, start_year: int, weeks_per_year: int) -> dict[str, int]:
    """Committed checkpoint only: never infer progress from logs or in-flight weeks."""
    path = world_dir / "checkpoint.json"
    checkpoint = load_json(path)
    if not isinstance(checkpoint, dict):
        raise ValueError(f"No readable committed checkpoint: {path}")
    year, week = checkpoint.get("year"), checkpoint.get("week")
    if type(year) is not int or type(week) is not int:
        raise ValueError("Checkpoint must contain integer year and week")
    if weeks_per_year < 1 or not (start_year <= year <= start_year + 100_000):
        raise ValueError("Checkpoint year or simulation calendar is invalid")
    if not (0 <= week <= weeks_per_year):
        raise ValueError("Checkpoint week is outside the configured simulation year")
    return {
        "weeks_completed": (year - start_year) * weeks_per_year + week,
        "checkpoint_year": year,
        "checkpoint_week": week,
    }


def _profile(root: Path, world: str, profile_path: Path | None) -> dict[str, Any]:
    if profile_path and profile_path.is_file():
        profile = load_json(profile_path)
    else:
        standard = root / "research" / "world_profile.json"
        if standard.exists():
            profile = load_json(standard)
        elif world == "detroit_persistent":
            # Detroit already explicitly opted in and published a public beacon.
            # Reuse its public metadata; do NOT substitute old checkpoint values.
            profile = load_json(root / "research" / "submissions" / "detroit.json")
        else:
            profile = None
    if not isinstance(profile, dict):
        raise ValueError("World profile missing. Create research/world_profile.json")
    required = ("world_id", "world_name", "maintainer", "repository", "simulated_context")
    if not all(profile.get(k) for k in required):
        raise ValueError("World profile is missing required public metadata")
    if profile.get("consent", {}).get("public_research_evaluation", True) is not True:
        raise ValueError("Public research evaluation is not permitted for this world")
    return profile


def build_beacon(root: Path = ROOT, world: str = "detroit_persistent",
                 profile_path: Path | None = None) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    if not world or not all(ch.isalnum() or ch in "_-" for ch in world):
        raise ValueError("Invalid world directory name")
    world_dir = root / "data" / world
    if not world_dir.is_dir():
        raise ValueError("World data directory does not exist")
    profile = _profile(root, world, profile_path)
    config = load_json(world_dir / "config.json", {})
    time_cfg = (config.get("world", {}).get("time", {}) if isinstance(config, dict)
                and isinstance(config.get("world"), dict) else {})
    if not isinstance(time_cfg, dict):
        time_cfg = {}
    start_year = int(profile.get("simulation_start_year") or time_cfg.get("start_year") or 2045)
    weeks_per_year = int(profile.get("weeks_per_year") or time_cfg.get("n_week") or 52)
    progress = valid_checkpoint(world_dir, start_year=start_year, weeks_per_year=weeks_per_year)

    persona = world_dir / "persona"
    total = 0
    active_fallback = 0
    if persona.is_dir():
        for p in persona.iterdir():
            if p.is_dir() and not p.is_symlink():
                total += 1
                if not (p / "_background.json").exists():
                    active_fallback += 1
    view = world_dir / ".active_persona_view"
    active = (sum(1 for p in view.iterdir() if p.is_dir() or p.is_symlink())
              if view.is_dir() else active_fallback)
    active = min(total, active)

    pack_ids: list[str] = []
    for p in sorted((root / "research" / "packs").glob("*.json")):
        obj = load_json(p, {})
        if isinstance(obj, dict) and obj.get("pack_id"):
            pack_ids.append(str(obj["pack_id"]))

    context = load_json(world_dir / "world_context" / "summary.json", {})
    environment = {}
    if isinstance(context, dict) and context:
        season = context.get("season") or {}
        weather = context.get("weather") or {}
        research = context.get("research") or {}
        environment = {
            "season": season.get("name"),
            "climate_profile": season.get("climate_profile"),
            "weather_condition": weather.get("condition"),
            "calendar_packs": [str(x["calendar_id"]) for x in context.get("calendar_packs", [])
                               if isinstance(x, dict) and x.get("calendar_id")],
            "synthetic_weather": bool(research.get("synthetic_weather", True)),
            "culture_inference": bool(research.get("culture_inference", False)),
        }

    return {
        "schema_version": "1.0",
        "world_id": profile["world_id"],
        "world_name": profile["world_name"],
        "maintainer": profile["maintainer"],
        "repository": profile["repository"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "simulated_context": profile["simulated_context"],
        "progress": progress,
        "population": {"total": total, "active": active},
        "hardware": {
            "profile": profile.get("hardware_profile", os.environ.get("AGENTOPIA_PROFILE", "unknown")),
            "platform": platform.system().lower(),
            "logical_cpus": max(1, os.cpu_count() or 1),
            "memory_gb": memory_gb(),
        },
        "right_sizing": aggregate_right_sizing(root / "runtime" / "right_sizing_requests.jsonl"),
        "environment": environment,
        "research_packs": pack_ids,
        "consent": {
            "public_research_evaluation": True,
            "model_training_finetuning": bool(profile.get("model_training_finetuning", False)),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export a privacy-safe Agentopia World Beacon.")
    ap.add_argument("--world", default="detroit_persistent")
    ap.add_argument("--profile", default="", help="Optional profile; Detroit can reuse published metadata")
    ap.add_argument("--output", default="")
    ap.add_argument("--agentopia-root", type=Path, default=ROOT)
    args = ap.parse_args()
    root = args.agentopia_root.expanduser().resolve()
    try:
        beacon = build_beacon(root, args.world, Path(args.profile) if args.profile else None)
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    output = (Path(args.output) if args.output else
              root / "research" / "submissions" / f"{beacon['world_id']}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(beacon, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output)
    progress = beacon["progress"]
    print(f"WROTE {output} | COMMITTED: {progress['weeks_completed']} weeks"
          f" Y{progress['checkpoint_year']} W{progress['checkpoint_week']}")
    print("PRIVACY: aggregate metadata only; prompts/responses are not exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
