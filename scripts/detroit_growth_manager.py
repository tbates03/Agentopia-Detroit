#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
HUM = WORLD / "humanity"
PERSONA = WORLD / "persona"
STATE_PATH = HUM / "promotion_state.json"
VERSION = "1.1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

TRAIT_KEYS = [
    "confidence", "control", "curiosity", "empathy", "judging",
    "introversion", "intuition", "patience", "responsibility", "thinking",
]
TALENT_KEYS = [
    "beauty", "communication", "creativity", "health", "honesty",
    "integrity", "intelligence", "leadership", "trustworthiness",
]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def stable_int(*parts: Any, lo: int, hi: int) -> int:
    raw = "|".join(map(str, parts))
    n = int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)
    return lo + (n % (hi - lo + 1))


def growth_config() -> dict[str, Any]:
    cfg = read_json(WORLD / "config.json", {})
    world = cfg.get("world") if isinstance(cfg, dict) else {}
    growth = world.get("growth") if isinstance(world, dict) else {}
    return growth if isinstance(growth, dict) else {}


def current_year() -> int:
    cp = read_json(WORLD / "checkpoint.json", {})
    if isinstance(cp, dict):
        try:
            return int(cp.get("year", 2045))
        except Exception:
            pass
    cfg = read_json(WORLD / "config.json", {})
    try:
        return int(cfg["world"]["time"]["start_year"])
    except Exception:
        return 2045


def recommend_active_target(total_personas: int) -> int:
    """Return a bounded AI-active cohort while allowing the city to keep growing.

    Background population can be much larger than the active LLM cohort. As the
    promoted persona population grows, the active cohort expands gradually.
    Explicit AGENTOPIA_ACTIVE_CITIZENS always wins.
    """
    if total_personas <= 0:
        return 0

    explicit = os.environ.get("AGENTOPIA_ACTIVE_CITIZENS")
    if explicit:
        try:
            return max(1, min(total_personas, int(explicit)))
        except Exception:
            pass

    growth = growth_config()
    minimum = int(os.environ.get("AGENTOPIA_ACTIVE_MIN", growth.get("active_ai_min", 64)))
    maximum = int(os.environ.get("AGENTOPIA_ACTIVE_MAX", growth.get("active_ai_max", 128)))
    minimum = max(1, minimum)
    maximum = max(minimum, maximum)

    # Half of the promoted persona population, bounded by the local-compute
    # operating envelope. 100 personas -> 64 active; 200 -> 100; 256+ -> 128.
    target = max(minimum, int(math.ceil(total_personas * 0.5)))
    return min(total_personas, maximum, target)


def _numeric_map(person_id: str, keys: list[str], lo: int, hi: int, domain: str) -> dict[str, int]:
    return {k: stable_int(domain, person_id, k, lo=lo, hi=hi) for k in keys}


def _lineage_text(person: dict[str, Any]) -> str:
    lineage = person.get("lineage")
    if isinstance(lineage, dict):
        ids = [str(x) for x in lineage.get("founder_ids", []) if x]
        if ids:
            return " Their recorded lineage connects to Agentopia Detroit founding-citizen IDs: " + ", ".join(ids) + "."
    return ""


def build_profile(person: dict[str, Any], year: int) -> dict[str, Any]:
    """Create a minimum complete Agentopia persona profile from explicit lifecycle data.

    No race, ethnicity, religion, gender, culture, or appearance is inferred from
    a name or origin. Missing identity fields remain unspecified.
    """
    pid = str(person.get("person_id") or "")
    name = str(person.get("name") or "Agentopia Citizen")
    birth_year = int(person.get("birth_year", year - int(person.get("age", 30) or 30)))
    age = max(0, year - birth_year)
    origin = str(person.get("origin") or "Agentopia Detroit")
    life_stage = str(person.get("life_stage") or "resident")

    traits = _numeric_map(pid, TRAIT_KEYS, 35, 78, "trait")
    talents = _numeric_map(pid, TALENT_KEYS, 35, 75, "talent")
    skills = {
        "communication": stable_int("skill", pid, "communication", lo=20, hi=75),
        "digital_literacy": stable_int("skill", pid, "digital_literacy", lo=15, hi=75),
        "daily_living": stable_int("skill", pid, "daily_living", lo=25, hi=80),
    }
    deposit = stable_int("assets", pid, "deposit", lo=500, hi=5000)

    lineage = person.get("lineage") if isinstance(person.get("lineage"), dict) else {}
    origin_obj = person.get("origin_record") if isinstance(person.get("origin_record"), dict) else {}

    details = (
        "AGENTOPIA DETROIT GROWTH: This citizen was promoted from the persistent "
        "background population into the interactive AI cohort. Identity fields that "
        "were not explicitly present in the lifecycle record remain unspecified."
        + _lineage_text(person)
    )

    profile: dict[str, Any] = {
        "name": name,
        "gender": "unspecified",
        "age": age,
        "birth_year": birth_year,
        "birthday": f"Y{birth_year}-W01-activity-D1",
        "birthday_source": "synthetic_default_week_only",
        "appearance_and_impression": (
            "This resident's detailed physical appearance has not been modeled. "
            "Agentopia does not infer appearance or protected identity from a name, origin, or family record."
        ),
        "brief_introduction": (
            f"{name} is a {life_stage.replace('_', ' ')} resident of Agentopia Detroit. "
            f"The explicit lifecycle record lists their prior origin as {origin}. "
            "They have entered the interactive civic simulation after existing in the background population."
        ),
        "details": details,
        "conflicts": (
            "They are adapting from background civic life to a more visible role in Agentopia while balancing "
            "work, relationships, finances, health, learning, and community obligations."
        ),
        "core_motivation": (
            "Build a stable, self-directed life in Agentopia Detroit and make choices that reflect lived experience."
        ),
        "values": (
            "Personal agency, family and community relationships, practical stability, learning, privacy, and accountability."
        ),
        "personality_traits": {
            "qualitative": (
                "An independently simulated citizen whose personality will evolve through choices, relationships, "
                "successes, setbacks, and accumulated memory rather than demographic stereotypes."
            ),
            "quantitative": traits,
        },
        "preferences": (
            "Preferences begin lightly specified and should become more individual through simulated experience. "
            "Do not infer preferences from origin, religion, race, ethnicity, gender, or name."
        ),
        "talents": {
            "qualitative": (
                "General human capabilities are seeded conservatively; specific strengths should emerge through the simulation."
            ),
            "quantitative": talents,
        },
        "position": {
            "weekly_income": 0,
            "role": "Civic Resident / Job Seeker",
            "organization": "Agentopia Detroit Civic Registry",
            "type": "unemployed",
            "description": "Growth-pool entry state; Detroit Career Economy is authoritative for future work.",
            "weekly_delta_skills": {},
        },
        "init_skills": skills,
        "init_assets": {"deposit": deposit, "possessions": []},
        "extra_income": 0,
        "growth_source": {
            "version": VERSION,
            "person_id": pid,
            "promoted_year": year,
            "source": "humanity_background_population",
        },
    }

    if person.get("founder_id"):
        profile["founder_id"] = person["founder_id"]
    if lineage:
        profile["lineage"] = lineage
    if origin_obj:
        profile["origin"] = origin_obj
    else:
        profile["origin"] = {"category": str(person.get("origin_type") or "resident"), "description": origin}
    return profile


def ensure_profile_years(year: int | None = None) -> int:
    """Carry persistent persona profiles forward for citizens inactive at year-end.

    Active citizens receive LLM-evolved yearly profiles from Agentopia core.
    Background personas do not, so without this carry-forward they could never
    safely re-enter the active cohort in a later year.
    """
    year = int(year or current_year())
    if not PERSONA.exists():
        return 0
    copied = 0
    for pdir in sorted((p for p in PERSONA.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        profdir = pdir / "profile"
        target = profdir / f"year={year}.json"
        if target.exists():
            continue
        files = sorted(profdir.glob("year=*.json")) if profdir.exists() else []
        candidates: list[tuple[int, Path]] = []
        for f in files:
            try:
                y = int(f.stem.split("=", 1)[1])
            except Exception:
                continue
            if y <= year:
                candidates.append((y, f))
        if not candidates:
            continue
        _, source = max(candidates, key=lambda x: x[0])
        profile = read_json(source, {})
        if not isinstance(profile, dict) or not profile:
            continue
        profile = dict(profile)
        profile["profile_carry_forward"] = {
            "source_year": int(source.stem.split("=", 1)[1]),
            "target_year": year,
            "reason": "background_persona_continuity",
        }
        write_json(target, profile)
        copied += 1
    return copied


def promote_background_people(year: int | None = None) -> list[str]:
    year = int(year or current_year())
    growth = growth_config()
    budget = int(os.environ.get("AGENTOPIA_PROMOTIONS_PER_YEAR", growth.get("promotions_per_year", 4)))
    budget = max(0, budget)
    if budget == 0:
        return []

    people_path = HUM / "people.json"
    people = read_json(people_path, {})
    if not isinstance(people, dict) or not people:
        return []

    state = read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    processed_years = state.setdefault("processed_years", {})
    year_key = str(year)
    already = [str(x) for x in processed_years.get(year_key, [])]
    remaining = max(0, budget - len(already))
    if remaining <= 0:
        return []

    candidates: list[tuple[str, dict[str, Any]]] = []
    for pid, person in people.items():
        if not isinstance(person, dict) or not person.get("alive", True):
            continue
        if person.get("agentopia_persona"):
            continue
        age = int(person.get("age", 0) or 0)
        if age < 18:
            continue
        name = str(person.get("name") or "").strip()
        if not name:
            continue
        candidates.append((str(pid), person))

    def rank(item: tuple[str, dict[str, Any]]) -> str:
        pid, _ = item
        return hashlib.sha256(f"promotion|{year}|{pid}".encode("utf-8")).hexdigest()

    promoted: list[str] = []
    PERSONA.mkdir(parents=True, exist_ok=True)
    for pid, person in sorted(candidates, key=rank):
        if len(promoted) >= remaining:
            break
        name = str(person["name"]).strip()
        pdir = PERSONA / name
        profile_path = pdir / "profile" / f"year={year}.json"

        # If a persona already exists, reconcile lifecycle state instead of overwriting it.
        existing_profiles = list((pdir / "profile").glob("year=*.json")) if (pdir / "profile").exists() else []
        if existing_profiles:
            person["agentopia_persona"] = True
            person["promoted_year"] = min(year, int(person.get("promoted_year", year)))
            continue

        profile = build_profile(person, year)
        write_json(profile_path, profile)
        write_json(
            pdir / "_background.json",
            {
                "reason": "growth_pool",
                "promoted_year": year,
                "person_id": pid,
                "note": "Persistent persona eligible for bounded active-cohort selection.",
            },
        )
        person["agentopia_persona"] = True
        person["promoted_year"] = year
        person["updated_at"] = utc_now()
        promoted.append(name)
        already.append(pid)

    if promoted:
        write_json(people_path, people)

    processed_years[year_key] = already
    state.update({
        "version": VERSION,
        "last_year": year,
        "last_promoted_names": promoted,
        "total_persona_dirs": len([p for p in PERSONA.iterdir() if p.is_dir()]) if PERSONA.exists() else 0,
    })
    write_json(STATE_PATH, state)
    return promoted


def prepare_for_boot() -> dict[str, Any]:
    """Refresh lifecycle truth, promote a bounded cohort, and report target size."""
    try:
        import detroit_human_lifecycle as humanity
        humanity.update()
    except Exception:
        pass

    year = current_year()
    carried_forward = ensure_profile_years(year)
    promoted = promote_background_people(year)

    # AGENTOPIA_CIVILIZATION_STORE_RC2
    # JSON remains the migration/debug source while SQLite provides indexed
    # population/state lookup and the append-only civilization event ledger.
    store_summary = {}
    try:
        import detroit_state_store as _state_store
        store_summary = _state_store.sync_legacy_state()
        if promoted:
            conn = _state_store.connect()
            people = read_json(HUM / "people.json", {})
            by_name = {
                str(p.get("name") or ""): str(pid)
                for pid, p in people.items()
                if isinstance(p, dict)
            } if isinstance(people, dict) else {}
            with _state_store.transaction(conn):
                for name in promoted:
                    _state_store.append_event(
                        conn,
                        "persona_promoted",
                        sim_year=year,
                        subject_id=by_name.get(name),
                        payload={"name": name},
                        source="detroit_growth_manager",
                        importance=1.5,
                        dedupe_key=f"persona-promoted:{year}:{name}",
                    )
            conn.close()
    except Exception as store_error:
        store_summary = {"warning": str(store_error)}

    total_personas = len([p for p in PERSONA.iterdir() if p.is_dir()]) if PERSONA.exists() else 0
    target = recommend_active_target(total_personas)
    result = {
        "version": VERSION,
        "world_year": year,
        "profiles_carried_forward": carried_forward,
        "promoted": promoted,
        "persona_population": total_personas,
        "recommended_active_ai": target,
        "civilization_store": store_summary,
    }
    write_json(HUM / "growth_summary.json", result)
    return result


def status() -> None:
    result = prepare_for_boot()
    print(f"Agentopia Detroit Growth Manager v{VERSION}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    status()
