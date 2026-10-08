#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import detroit_state_store as store
from detroit_relevance_activation import select_names


def run(citizens: int, personas: int, events: int, max_seconds: float) -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="agentopia-rc2-") as td:
        db = Path(td) / "civilization.sqlite3"
        conn = store.connect(db)
        now = store.utc_now()
        rows = []
        duplicate_name = "Alex Johnson"
        for i in range(citizens):
            display_name = duplicate_name if i in (citizens - 2, citizens - 1) else f"Citizen {i:09d}"
            rows.append((
                f"CIV-{i:09d}", display_name, 1, 1980 + (i % 60),
                "adult", "synthetic_stress", "", "[]", int(i < personas),
                2045 if i < personas else None, "stress_harness", now,
            ))

        with store.transaction(conn):
            store.bulk_seed_citizens(conn, rows)
            for i in range(events):
                subject = f"CIV-{i % max(1, personas):09d}"
                store.append_event(
                    conn,
                    "job_changed" if i % 3 else "faction_joined",
                    sim_year=2045 + (i % 3),
                    sim_week=(i % 52) + 1,
                    subject_id=subject,
                    importance=1.0 + (i % 5) / 10.0,
                    source="stress_harness",
                    dedupe_key=f"stress:{i}",
                )

        stats = store.store_stats(conn)
        conn.close()
        names = [f"Citizen {i:09d}" for i in range(personas)]
        selected = select_names(names, target=min(128, personas), year=2047, db_path=db)
        elapsed = time.perf_counter() - started

        result = {
            "citizens_requested": citizens,
            "personas_requested": personas,
            "events_requested": events,
            "selected_active": len(selected),
            "elapsed_seconds": round(elapsed, 3),
            "max_seconds": max_seconds,
            "within_budget": elapsed <= max_seconds,
            "duplicate_name_rows": 2,
            "stats": stats,
        }

        if stats["citizens"] != citizens:
            raise RuntimeError(f"citizen count mismatch: {stats['citizens']} != {citizens}")
        if stats["events"] != events:
            raise RuntimeError(f"event count mismatch: {stats['events']} != {events}")
        dup_conn = store.connect(db)
        duplicate_rows = dup_conn.execute(
            "SELECT COUNT(*) FROM citizens WHERE name=? COLLATE NOCASE",
            (duplicate_name,),
        ).fetchone()[0]
        dup_conn.close()
        if duplicate_rows != 2:
            raise RuntimeError(f"duplicate-name identity regression: expected 2 rows, found {duplicate_rows}")
        if len(selected) != min(128, personas):
            raise RuntimeError("active-cohort selection mismatch")
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Headless scale harness for Agentopia Detroit civilization state")
    ap.add_argument("--citizens", type=int, default=100_000)
    ap.add_argument("--personas", type=int, default=1_000)
    ap.add_argument("--events", type=int, default=10_000)
    ap.add_argument("--max-seconds", type=float, default=30.0)
    args = ap.parse_args()
    result = run(args.citizens, args.personas, args.events, args.max_seconds)
    print(json.dumps(result, indent=2))
    return 0 if result["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
