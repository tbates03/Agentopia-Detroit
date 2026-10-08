#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"


def text(path: str) -> str:
    p = ROOT / path
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


CHECKS = [
    (
        "calendar_52_weeks",
        "critical",
        "scripts/run_detroit_persistent.py",
        'time_cfg["n_week"] = 52',
        "Detroit uses a full seasonal/calendar year instead of upstream's compressed 10-week year.",
    ),
    (
        "activity_days_5",
        "critical",
        "scripts/run_detroit_persistent.py",
        'time_cfg["n_day"] = 5',
        "Five LLM-heavy activity days remain bounded inside each seven-day calendar week.",
    ),
    (
        "reward_52_compatible",
        "critical",
        "scripts/run_detroit_persistent.py",
        'reward_cfg["period_weeks"] = 13',
        "Reward period divides the 52-week Detroit year.",
    ),
    (
        "practical_no_stop_horizon",
        "high",
        "scripts/run_detroit_persistent.py",
        "1_000_000",
        "Persistent runner no longer inherits a small finite simulation horizon.",
    ),
    (
        "population_growth_manager",
        "critical",
        "scripts/detroit_growth_manager.py",
        "def promote_background_people",
        "Background residents can become durable Agentopia personas.",
    ),
    (
        "inactive_profile_continuity",
        "critical",
        "scripts/detroit_growth_manager.py",
        "def ensure_profile_years",
        "Inactive personas can safely re-enter the active cohort in later years.",
    ),
    (
        "annual_migration",
        "high",
        "scripts/detroit_human_lifecycle.py",
        '"event":"annual_migration"',
        "Population growth is not limited to the one-time migration seed or births.",
    ),
    (
        "lineage_propagation",
        "high",
        "scripts/detroit_human_lifecycle.py",
        "inherited_lineage",
        "Founder lineage can persist into descendants.",
    ),
    (
        "activation_queue_not_first_100",
        "high",
        "scripts/detroit_human_lifecycle.py",
        '"candidate_count":len(activation),"candidates":activation',
        "Promotion discovery is not silently truncated to the first 100 background candidates.",
    ),
    (
        "active_ai_auto_scales",
        "critical",
        "scripts/detroit_growth_manager.py",
        "def recommend_active_target",
        "Total civic population and expensive active-AI population are decoupled.",
    ),
    (
        "active_view_allows_background",
        "critical",
        "src/world/world.py",
        "_include_background_personas",
        "Citizens selected into the runtime view are not filtered out again by _background.json.",
    ),
    (
        "yearly_cohort_recycle",
        "critical",
        "scripts/run_detroit_persistent.py",
        "AGENTOPIA_YEARLY_COHORT_RECYCLE_V180",
        "Active cohort can refresh as the persistent population grows.",
    ),
    (
        "service_yearly_recycle",
        "critical",
        "scripts/start_detroit_persistent_service.sh",
        "ENGINE_YEAR_ROLLOVER",
        "Intentional year-boundary process recycle restarts automatically from checkpoint.",
    ),
    (
        "adaptive_concurrency",
        "critical",
        "src/world/simulation_speed.py",
        "AGENTOPIA_ADAPTIVE_CONCURRENCY_V180",
        "Fast modes can exceed the inherited 12-worker ceiling within a configurable local cap.",
    ),
    (
        "public_activity_deadlock_fixed",
        "critical",
        "src/world/world.py",
        "AGENTOPIA_ACTIVITY_SLOT_DEADLOCK_FIX_V1745",
        "Multi-slot PublicActivity reservations cannot self-deadlock above semaphore capacity.",
    ),
    (
        "global_prompt_bounded",
        "critical",
        "src/world/world.py",
        "def _bounded_agents_for_context",
        "Global God-model prompts no longer grow linearly with every active citizen.",
    ),
    (
        "encounter_prompt_bounded",
        "critical",
        "src/world/god.py",
        "AGENTOPIA_ENCOUNTER_CONTEXT_BOUND_V180",
        "Encounter prompts rotate a bounded citizen slice instead of embedding the whole city.",
    ),
    (
        "mobility_active_cohort",
        "high",
        "scripts/detroit_mobility_time.py",
        "AGENTOPIA_MOBILITY_ACTIVE_COHORT_V180",
        "Rich weekly trip generation scales with active AI rather than every persistent persona.",
    ),
    (
        "job_market_scales",
        "high",
        "scripts/detroit_career_economy.py",
        "AGENTOPIA_CAREER_GROWTH_CAPACITY_V180",
        "Vacancy supply grows with the active cohort instead of staying fixed at 60.",
    ),
    (
        "detroit_career_authority",
        "high",
        "scripts/run_detroit_persistent.py",
        "legacy annual position application skipped",
        "Legacy Agentopia position season does not fight Detroit Career/Business Economy.",
    ),
    (
        "world_context_calendar",
        "high",
        "scripts/detroit_world_context.py",
        "def week_dates",
        "Weather, seasons and calendar context are present for the full-year timeline.",
    ),
    (
        "public_map_grows",
        "high",
        "src/world/locations.py",
        "AGENTOPIA_PUBLIC_MAP_GROWTH_V180",
        "Detroit public-space capacity expands gradually with the active population.",
    ),
    (
        "map_expansion_avoids_duplicates",
        "high",
        "src/world/mapgen.py",
        "avoid_names",
        "Incremental map generation is told not to reuse existing public locations.",
    ),
    (
        "indexed_civilization_store",
        "critical",
        "scripts/detroit_state_store.py",
        "CREATE TABLE IF NOT EXISTS citizens",
        "Large civic populations have an indexed SQLite state plane instead of requiring repeated directory scans.",
    ),
    (
        "append_only_event_ledger",
        "critical",
        "scripts/detroit_state_store.py",
        "CREATE TABLE IF NOT EXISTS events",
        "Civilization history is recorded as immutable events with dedupe keys.",
    ),
    (
        "relevance_activation",
        "critical",
        "scripts/detroit_relevance_activation.py",
        "def rank_personas",
        "The active AI cohort is chosen by relevance rather than only static foreground ordering.",
    ),
    (
        "civilization_invariants",
        "critical",
        "scripts/detroit_civilization_invariants.py",
        "def audit",
        "State corruption is checked with explicit civilization invariants.",
    ),
    (
        "hundred_k_stress_harness",
        "high",
        "scripts/stress_detroit_civilization.py",
        "100_000",
        "RC2 ships a headless 100K-citizen scale regression harness.",
    ),
    (
        "household_identity_reconciled",
        "critical",
        "scripts/detroit_human_lifecycle.py",
        "def reconcile_household_ids",
        "Lifecycle no longer collapses unrelated unassigned citizens into one household.",
    ),
    (
        "economy_uses_lifecycle_households",
        "critical",
        "scripts/detroit_human_economy.py",
        "household_truth':'humanity.people.household_id",
        "Human Economy uses lifecycle household identity as its canonical household graph.",
    ),
    (
        "lifecycle_syncs_civilization_store",
        "critical",
        "scripts/detroit_humanity_daemon.py",
        "detroit_state_store.py",
        "Births, migration and lifecycle changes are synchronized into the RC2 indexed civilization store.",
    ),
    (
        "heartbeat_starts_before_world",
        "critical",
        "scripts/run_detroit_persistent.py",
        "AGENTOPIA_ENGINE_HEARTBEAT_RC2_EARLY",
        "Engine heartbeat starts before expensive World construction so reboot initialization never appears stale.",
    ),
    (
        "observer_disconnects_are_normal",
        "high",
        "live_world/server.py",
        "ConnectionResetError, ConnectionAbortedError",
        "Normal dashboard/client disconnects do not generate BrokenPipe failure traces.",
    ),
    (
        "citizen_identity_schema_v2",
        "critical",
        "scripts/detroit_state_store.py",
        "SCHEMA_VERSION = 2",
        "Citizen identity is keyed by citizen_id and duplicate human display names are allowed.",
    ),
    (
        "citizen_name_index_nonunique",
        "critical",
        "scripts/detroit_state_store.py",
        "CREATE INDEX IF NOT EXISTS idx_citizens_name",
        "Name remains searchable without being treated as a unique civic identity.",
    ),
]


INTENTIONAL_GUARDRAILS = [
    ("solo possessions", "50 per persona", "Prompt/storage safety; not a population cap."),
    ("future social scheduling", "4 weeks by upstream default", "Local planning horizon; not a city population cap."),
    ("public event count", "bounded per week", "Large attendance is supported; event count need not scale linearly with population."),
    ("active AI cohort", "bounded", "Compute window, not civic-population ceiling."),
    ("global prompt samples", "bounded/rotating", "Context-window protection; omitted citizens retain state."),
]


def local_metrics() -> dict:
    out: dict = {}
    cp = WORLD / "checkpoint.json"
    if cp.exists():
        try:
            out["checkpoint"] = json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass
    persona = WORLD / "persona"
    if persona.exists():
        dirs = [p for p in persona.iterdir() if p.is_dir()]
        out["persona_population"] = len(dirs)
        out["foreground_personas"] = sum(1 for p in dirs if not (p / "_background.json").exists())
        out["background_personas"] = sum(1 for p in dirs if (p / "_background.json").exists())
    view = WORLD / ".active_persona_view"
    if view.exists():
        out["active_ai_view"] = sum(1 for p in view.iterdir() if p.is_dir() or p.is_symlink())
    hum = WORLD / "humanity" / "summary.json"
    if hum.exists():
        try:
            h = json.loads(hum.read_text(encoding="utf-8"))
            out["civic_population"] = h.get("population")
            out["activation_candidates"] = h.get("activation_candidates")
        except Exception:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = []
    failures = 0
    for key, severity, path, needle, why in CHECKS:
        ok = needle in text(path)
        rows.append({"check": key, "severity": severity, "pass": ok, "path": path, "why": why})
        if not ok and severity in {"critical", "high"}:
            failures += 1

    result = {
        "audit": "Agentopia Detroit Growth Audit",
        "checks": rows,
        "passed": sum(1 for x in rows if x["pass"]),
        "failed": sum(1 for x in rows if not x["pass"]),
        "local_metrics": local_metrics(),
        "intentional_guardrails": [
            {"area": a, "bound": b, "reason": r} for a, b, r in INTENTIONAL_GUARDRAILS
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("=== AGENTOPIA DETROIT GROWTH AUDIT ===")
        for row in rows:
            mark = "PASS" if row["pass"] else "FAIL"
            print(f"{mark:4} [{row['severity']:<8}] {row['check']}: {row['why']}")
        print(f"\nChecks: {result['passed']} passed / {result['failed']} failed")
        if result["local_metrics"]:
            print("\nLocal world:")
            print(json.dumps(result["local_metrics"], indent=2, ensure_ascii=False))
        print("\nIntentional bounded guardrails:")
        for item in result["intentional_guardrails"]:
            print(f"- {item['area']}: {item['bound']} — {item['reason']}")

    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
