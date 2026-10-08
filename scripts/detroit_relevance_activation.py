#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import detroit_state_store as store

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"

HIGH_SIGNAL_TYPES = {
    "mission_assigned": 70.0,
    "legal_case_opened": 65.0,
    "arrested": 70.0,
    "faction_joined": 55.0,
    "faction_leadership": 85.0,
    "business_started": 45.0,
    "business_closed": 45.0,
    "major_health_event": 50.0,
    "relationship_major": 35.0,
    "job_changed": 25.0,
    "education_milestone": 20.0,
    "migration": 15.0,
    "birth": 10.0,
}
PINNED = {"TGOT", "Morbeious"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tie(name: str, year: int) -> float:
    n = int(hashlib.sha256(f"activate|{year}|{name.casefold()}".encode()).hexdigest()[:12], 16)
    return (n % 1000000) / 1000000.0


def _event_score(conn, citizen_id: str, year: int) -> tuple[float, list[str]]:
    rows = conn.execute(
        """
        SELECT event_type,importance,sim_year,sim_week FROM events
        WHERE subject_id=? AND (sim_year IS NULL OR sim_year>=?)
        ORDER BY COALESCE(sim_year,0) DESC, COALESCE(sim_week,0) DESC LIMIT 40
        """,
        (citizen_id, year - 2),
    ).fetchall()
    score = 0.0
    reasons: list[str] = []
    for row in rows:
        eyear = int(row["sim_year"] or year)
        age = max(0, year - eyear)
        decay = 1.0 / (1.0 + age)
        base = HIGH_SIGNAL_TYPES.get(str(row["event_type"]), 8.0)
        points = base * float(row["importance"] or 1.0) * decay
        score += points
        if points >= 15 and len(reasons) < 6:
            reasons.append(str(row["event_type"]))
    return score, reasons


def rank_personas(
    persona_names: Iterable[str],
    *,
    target: int,
    year: int,
    pinned_names: Iterable[str] = (),
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    names = sorted({str(n) for n in persona_names if str(n).strip()}, key=str.casefold)
    if not names or target <= 0:
        return []

    conn = store.connect(db_path)
    pinned = PINNED | {str(x) for x in pinned_names}
    ranked: list[dict[str, Any]] = []

    for name in names:
        row = store.resolve_persona_citizen(conn, name)
        cid = str(row["citizen_id"]) if row else "persona:" + hashlib.sha256(name.casefold().encode()).hexdigest()[:20]
        score = 25.0
        reasons = ["persistent_persona"]
        if row and not bool(row["alive"]):
            score -= 10000.0
            reasons.append("not_alive")
        if name in pinned:
            score += 10000.0
            reasons.append("pinned")
        event_points, event_reasons = _event_score(conn, cid, year)
        score += event_points
        reasons.extend(event_reasons)
        if row and row["promoted_year"] is not None and int(row["promoted_year"]) >= year - 1:
            score += 12.0
            reasons.append("recently_promoted")
        score += _tie(name, year)
        ranked.append({"name": name, "citizen_id": cid, "score": score, "reasons": reasons})

    ranked.sort(key=lambda x: (-x["score"], x["name"].casefold()))
    selected = ranked[: min(target, len(ranked))]
    now = utc_now()

    with store.transaction(conn):
        for item in ranked:
            conn.execute(
                """
                INSERT INTO activation_scores(citizen_id,score,reasons_json,scored_at,sim_year)
                VALUES(?,?,?,?,?)
                ON CONFLICT(citizen_id) DO UPDATE SET
                    score=excluded.score,reasons_json=excluded.reasons_json,
                    scored_at=excluded.scored_at,sim_year=excluded.sim_year
                """,
                (item["citizen_id"], item["score"], json.dumps(item["reasons"]), now, year),
            )
        store.append_event(
            conn,
            "active_cohort_selected",
            sim_year=year,
            payload={"target": target, "selected_names": [x["name"] for x in selected]},
            source="detroit_relevance_activation",
            importance=0.5,
            dedupe_key=f"active-cohort:{year}:" + hashlib.sha256("|".join(x["name"] for x in selected).encode()).hexdigest()[:16],
        )

    conn.close()
    return selected


def select_names(
    persona_names: Iterable[str],
    *,
    target: int,
    year: int,
    pinned_names: Iterable[str] = (),
    db_path: Path | str | None = None,
) -> list[str]:
    return [x["name"] for x in rank_personas(
        persona_names, target=target, year=year, pinned_names=pinned_names, db_path=db_path
    )]


def main() -> int:
    ap = argparse.ArgumentParser(description="Select Agentopia Detroit active AI cohort by relevance")
    ap.add_argument("--target", type=int, default=128)
    ap.add_argument("--year", type=int, default=2045)
    ap.add_argument("--db", type=Path)
    args = ap.parse_args()
    persona_root = WORLD / "persona"
    names = [p.name for p in persona_root.iterdir() if p.is_dir()] if persona_root.exists() else []
    ranked = rank_personas(names, target=args.target, year=args.year, db_path=args.db)
    print(json.dumps(ranked, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
