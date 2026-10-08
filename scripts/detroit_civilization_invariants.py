#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import detroit_state_store as store

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def audit(db_path: Path | str | None = None, world: Path | None = None) -> dict[str, Any]:
    world = Path(world or WORLD)
    conn = store.connect(db_path or (world / "civilization.sqlite3"))
    checks: list[dict[str, Any]] = []

    def check(name: str, sql: str, why: str) -> None:
        rows = conn.execute(sql).fetchall()
        checks.append({"check": name, "pass": len(rows) == 0, "violations": len(rows), "why": why})

    check("citizen_ids_unique", "SELECT citizen_id FROM citizens GROUP BY citizen_id HAVING COUNT(*)>1", "Citizen IDs are immutable identities.")
    check("citizen_names_nonempty", "SELECT citizen_id FROM citizens WHERE TRIM(name)=''", "Every indexed citizen needs a display identity.")
    checks.append({
        "check": "duplicate_names_allowed",
        "pass": True,
        "violations": 0,
        "why": "Display names are not civic identity keys; citizen_id is authoritative.",
    })
    check("birth_year_plausible", "SELECT citizen_id FROM citizens WHERE birth_year IS NOT NULL AND (birth_year<1800 OR birth_year>1000000)", "Birth years must remain inside the simulation horizon.")
    check("event_importance_nonnegative", "SELECT event_id FROM events WHERE importance<0", "Event importance cannot invert relevance scoring.")
    check("persona_is_living", "SELECT citizen_id FROM citizens WHERE is_persona=1 AND alive=0", "Dead citizens must not remain eligible for active cognition.")
    check("promotion_not_before_birth", "SELECT citizen_id FROM citizens WHERE promoted_year IS NOT NULL AND birth_year IS NOT NULL AND promoted_year<birth_year", "Promotion cannot predate birth.")
    check("activation_scores_known_citizens", "SELECT a.citizen_id FROM activation_scores a LEFT JOIN citizens c USING(citizen_id) WHERE c.citizen_id IS NULL", "Every score must resolve to a citizen.")

    cp = _read(world / "checkpoint.json", {})
    if isinstance(cp, dict):
        year = int(cp.get("year", 0) or 0)
        week = int(cp.get("week", 0) or 0)
        checks.append({
            "check": "checkpoint_week_range",
            "pass": 1 <= week <= 52,
            "violations": 0 if 1 <= week <= 52 else 1,
            "why": "Detroit uses a 52-week calendar and checkpoint weeks must stay in range.",
        })
        checks.append({
            "check": "checkpoint_year_positive",
            "pass": year > 0,
            "violations": 0 if year > 0 else 1,
            "why": "Simulation time cannot move into an invalid year.",
        })

    result = {
        "audit": "Agentopia Detroit Civilization Invariants",
        "passed": sum(1 for x in checks if x["pass"]),
        "failed": sum(1 for x in checks if not x["pass"]),
        "checks": checks,
    }
    conn.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = audit(args.db)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("=== AGENTOPIA DETROIT CIVILIZATION INVARIANTS ===")
        for row in result["checks"]:
            print(f"{'PASS' if row['pass'] else 'FAIL':4} {row['check']}: {row['why']}")
        print(f"\nChecks: {result['passed']} passed / {result['failed']} failed")
    return 1 if args.strict and result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
