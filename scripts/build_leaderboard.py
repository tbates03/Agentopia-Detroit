#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ROOT / "research" / "submissions"
OUTPUT = ROOT / "LEADERBOARD.md"


def load_worlds() -> list[dict[str, Any]]:
    worlds = []
    seen = set()
    for path in sorted(SUBMISSIONS.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"Invalid JSON in {path}: {exc}")
        for key in ("world_id", "world_name", "maintainer", "repository", "progress", "simulated_context", "right_sizing", "consent"):
            if key not in row:
                raise SystemExit(f"{path}: missing required key {key}")
        if row["world_id"] in seen:
            raise SystemExit(f"duplicate world_id: {row['world_id']}")
        if row.get("consent", {}).get("public_research_evaluation") is not True:
            raise SystemExit(f"{path}: public_research_evaluation must be true")
        seen.add(row["world_id"])
        worlds.append(row)
    return worlds


def scale_for(n: int) -> str:
    if n >= 500:
        return "decades"
    if n >= 100:
        return "years"
    if n >= 25:
        return "months"
    return "weeks"


def display_progress(weeks: int, scale: str) -> str:
    if scale == "weeks":
        return f"{weeks} wk"
    if scale == "months":
        return f"{weeks // 4} mo / {weeks % 4} wk"
    if scale == "years":
        return f"{weeks // 52} yr / {(weeks % 52) // 4} mo"
    return f"{weeks // 520} dec / {(weeks % 520) // 52} yr"


def milestone(weeks: int) -> str:
    if weeks >= 520:
        return "Decade Civilization"
    if weeks >= 52:
        return "Year Architect"
    if weeks >= 4:
        return "Month Builder"
    if weeks >= 1:
        return "Week Runner"
    return "Starting Line"


def md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render(worlds: list[dict[str, Any]]) -> str:
    worlds = sorted(worlds, key=lambda w: (-int(w["progress"]["weeks_completed"]), str(w["world_name"]).lower()))
    scale = scale_for(len(worlds))
    lines = [
        "# Agentopia World League",
        "",
        f"**{len(worlds)} participating world{'s' if len(worlds) != 1 else ''} · display scale: {scale}**",
        "",
        "The leaderboard uses **committed checkpoints only**. In-flight weeks do not count.",
        "",
        "| Rank | World | Maintainer | Progress | Milestone | Languages | Research Packs |",
        "|---:|---|---|---:|---|---|---:|",
    ]
    for idx, w in enumerate(worlds, 1):
        weeks = int(w["progress"]["weeks_completed"])
        maint = md_escape(w["maintainer"].get("github", "unknown"))
        repo = md_escape(w["repository"])
        world = md_escape(w["world_name"])
        langs = ", ".join(md_escape(x.get("bcp47", "")) for x in w.get("simulated_context", {}).get("languages", [])) or "—"
        packs = len(w.get("research_packs", []))
        lines.append(f"| {idx} | [{world}]({repo}) | @{maint} | {display_progress(weeks, scale)} | {milestone(weeks)} | {langs} | {packs} |")

    lines += [
        "",
        "## Research Contribution View",
        "",
        "| World | 350M calls | 1.2B calls | 2.6B calls | Avg latency | Success |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for w in worlds:
        rs = w.get("right_sizing", {})
        counts = rs.get("requests_by_tier", {})
        avg = rs.get("avg_latency_ms")
        success = rs.get("success_percent")
        avg_text = "—" if avg is None else f"{float(avg):.1f} ms"
        success_text = "—" if success is None else f"{float(success):.1f}%"
        lines.append(f"| {md_escape(w['world_name'])} | {int(counts.get('350M', 0))} | {int(counts.get('1.2B', 0))} | {int(counts.get('2.6B', 0))} | {avg_text} | {success_text} |")

    lines += [
        "",
        "## Join the League",
        "",
        "Fork the project, build your own world, contribute tasks in the language they are actually performed in, and submit a privacy-safe World Beacon.",
        "",
        "See docs/WORLD_LEAGUE.md.",
        "",
        "_Generated from merged files in research/submissions/. The leaderboard itself contains no prompts, private conversations, credentials, or private world histories._",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if LEADERBOARD.md is not up to date")
    args = ap.parse_args()
    rendered = render(load_worlds())
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print("LEADERBOARD.md is out of date. Run: python scripts/build_leaderboard.py")
            return 1
        print("LEADERBOARD: PASS")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"WROTE {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
