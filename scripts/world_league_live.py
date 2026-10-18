"""Fast World League view assembled from committed local checkpoints.

No live-persona conversations, names, prompts or personal timelines exposed.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from export_world_beacon import build_beacon
from build_leaderboard import milestone, scale_for, display_progress


def league_snapshot(root: Path, world: str = "detroit_persistent") -> dict[str, Any]:
    root = Path(root).resolve()
    submissions = root / "research" / "submissions"
    worlds = {}
    for file in sorted(submissions.glob("*.json")):
        try:
            row = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and row.get("consent", {}).get("public_research_evaluation") is True:
            world_id = row.get("world_id")
            progress = row.get("progress") or {}
            if isinstance(world_id, str) and isinstance(progress.get("weeks_completed"), int):
                worlds[world_id] = row
    live = None
    warning = None
    try:
        live = build_beacon(root, world)
        worlds[live["world_id"]] = live
    except (OSError, ValueError, TypeError) as exc:
        warning = str(exc)
    entries = sorted(worlds.values(), key=lambda x: (-int(x["progress"]["weeks_completed"]), str(x.get("world_name", "")).lower()))
    scale = scale_for(len(entries))
    rows = []
    for rank, entry in enumerate(entries, 1):
        progress = entry["progress"]
        weeks = int(progress["weeks_completed"])
        rows.append({
            "rank": rank,
            "world_id": entry["world_id"],
            "world_name": entry["world_name"],
            "repository": entry.get("repository", ""),
            "maintainer": (entry.get("maintainer") or {}).get("github", ""),
            "weeks_completed": weeks,
            "checkpoint_year": progress.get("checkpoint_year"),
            "checkpoint_week": progress.get("checkpoint_week"),
            "display_progress": display_progress(weeks, scale),
            "milestone": milestone(weeks),
            "population": entry.get("population", {}),
            "generated_at": entry.get("generated_at"),
            "source": "live_committed_checkpoint" if live is not None and entry["world_id"] == live["world_id"] else "published_submission",
        })
    return {"ok": bool(entries), "scale": scale, "count": len(entries),
            "worlds": rows, "live_checkpoint_available": live is not None,
            "warning": warning, "publication": "local only; not pushed to GitHub"}
