#!/usr/bin/env python3
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
    except Exception:
        return default


def memory_gb() -> float | None:
    try:
        if sys.platform == "darwin":
            import subprocess
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return round(int(raw) / (1024 ** 3), 1)
        info = Path("/proc/meminfo")
        if info.exists():
            for line in info.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round((kb * 1024) / (1024 ** 3), 1)
    except Exception:
        pass
    return None


def aggregate_right_sizing(path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {"350M": 0, "1.2B": 0, "2.6B": 0}
    latencies: list[float] = []
    success = 0
    total = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            tier = str(row.get("tier") or "other")
            counts[tier] = counts.get(tier, 0) + 1
            try:
                latencies.append(max(0.0, float(row.get("latency_ms", 0) or 0)))
            except Exception:
                pass
            success += 1 if row.get("success") is True else 0
            total += 1
    return {
        "local_inference": True,
        "model_tiers": [k for k in ("350M", "1.2B", "2.6B") if k in counts],
        "requests_by_tier": counts,
        "success_percent": round((success / total) * 100.0, 1) if total else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export a privacy-safe Agentopia World Beacon.")
    ap.add_argument("--world", default="detroit_persistent")
    ap.add_argument("--profile", default=str(ROOT / "research" / "world_profile.json"))
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    profile_path = Path(args.profile)
    profile = load_json(profile_path)
    if not isinstance(profile, dict):
        print(f"ERROR: create {profile_path} from research/world_profile.example.json", file=sys.stderr)
        return 2

    world_dir = ROOT / "data" / args.world
    checkpoint = load_json(world_dir / "checkpoint.json", {})
    if not isinstance(checkpoint, dict) or "year" not in checkpoint or "week" not in checkpoint:
        print(f"ERROR: no committed checkpoint at {world_dir / 'checkpoint.json'}", file=sys.stderr)
        return 3

    start_year = int(profile.get("simulation_start_year", int(checkpoint["year"])))
    weeks_per_year = int(profile.get("weeks_per_year", 52))
    year = int(checkpoint["year"])
    week = int(checkpoint["week"])
    weeks_completed = max(0, (year - start_year) * weeks_per_year + week)

    population_total = population_active = 0
    persona = world_dir / "persona"
    if persona.exists():
        try:
            population_total = sum(1 for p in persona.iterdir() if p.is_dir())
        except Exception:
            pass
    active_view = world_dir / ".active_persona_view"
    if active_view.exists():
        try:
            population_active = sum(1 for p in active_view.iterdir() if p.is_dir() or p.is_symlink())
        except Exception:
            pass

    pack_ids: list[str] = []
    for p in sorted((ROOT / "research" / "packs").glob("*.json")):
        row = load_json(p, {})
        if isinstance(row, dict) and row.get("pack_id"):
            pack_ids.append(str(row["pack_id"]))

    world_context = load_json(world_dir / "world_context" / "summary.json", {})
    environment = {}
    if isinstance(world_context, dict) and world_context:
        environment = {
            "season": (world_context.get("season") or {}).get("name"),
            "climate_profile": (world_context.get("season") or {}).get("climate_profile"),
            "weather_condition": (world_context.get("weather") or {}).get("condition"),
            "calendar_packs": [
                str(x.get("calendar_id"))
                for x in (world_context.get("calendar_packs") or [])
                if isinstance(x, dict) and x.get("calendar_id")
            ],
            "synthetic_weather": bool((world_context.get("research") or {}).get("synthetic_weather", True)),
            "culture_inference": bool((world_context.get("research") or {}).get("culture_inference", False)),
        }

    beacon = {
        "schema_version": "1.0",
        "world_id": profile["world_id"],
        "world_name": profile["world_name"],
        "maintainer": profile["maintainer"],
        "repository": profile["repository"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "simulated_context": profile.get("simulated_context", {"languages": []}),
        "progress": {"weeks_completed": weeks_completed, "checkpoint_year": year, "checkpoint_week": week},
        "population": {"total": population_total, "active": population_active},
        "hardware": {
            "profile": profile.get("hardware_profile", os.environ.get("AGENTOPIA_PROFILE", "unknown")),
            "platform": platform.system().lower(),
            "logical_cpus": max(1, os.cpu_count() or 1),
            "memory_gb": memory_gb(),
        },
        "right_sizing": aggregate_right_sizing(ROOT / "runtime" / "right_sizing_requests.jsonl"),
        "environment": environment,
        "research_packs": pack_ids,
        "consent": {
            "public_research_evaluation": True,
            "model_training_finetuning": bool(profile.get("model_training_finetuning", False)),
        },
    }

    output = Path(args.output) if args.output else ROOT / "research" / "submissions" / f"{profile['world_id']}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(beacon, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {output}")
    print(f"COMMITTED PROGRESS: {weeks_completed} weeks (Y{year} W{week})")
    print("PRIVACY: aggregate metadata only; prompts/responses are not exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
