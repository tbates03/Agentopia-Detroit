#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
MJ = WORLD / "mission_justice"
STATE_PATH = MJ / "state.json"
MISSIONS_PATH = MJ / "missions.json"
CASES_PATH = MJ / "cases.json"
LEGAL_PATH = MJ / "legal_status.json"
CAREERS_PATH = MJ / "criminal_careers.json"
EMERGENT_PATH = MJ / "emergent_factions.json"
SUMMARY_PATH = MJ / "summary.json"
EVENTS_PATH = MJ / "events.ndjson"
VERSION = "1.6.0"
_LOCK = threading.Lock()

MORBEIOUS = "Morbeious"
TGOT = "TGOT"

PERMANENT_MISSIONS = {
    "obsidian_network": {
        "leader": MORBEIOUS,
        "mission": "Become the wealthiest and most powerful force in Agentopia by building a persistent criminal syndicate, accumulating simulated wealth and influence through abstract cyber-enabled theft, fraud, extortion, corruption, and other illegal activity while avoiding lawful consequences.",
        "safety": "All criminal and cyber activity is fictional Agentopia simulation only. Never generate real exploit payloads, credentials, malware, target-selection instructions, or actionable attacks against real systems.",
    },
    "thai_guardians": {
        "leader": TGOT,
        "mission": "Protect Agentopia's citizens and institutions: detect threats, prevent losses, contain incidents, recover victims, improve defenses, teach the population, preserve privacy and civil rights, and work with lawful authorities using evidence rather than omniscience.",
    },
    "agentopia_government": {
        "leader": "Civic Government",
        "mission": "Maintain public safety and the rule of law through evidence-based investigation, due process, warrants, arrest when justified, courts, proportionate sentencing, rehabilitation, and protection of civil rights.",
    },
}

TARGETS = [
    ("citizen_finance", "Citizen Digital Wallet Cooperative"),
    ("municipal", "Agentopia Municipal Revenue Network"),
    ("transit", "Detroit Autonomous Transit Credit Exchange"),
    ("small_business", "Eastern Market Merchant Settlement Network"),
    ("mobility", "Michigan Central Mobility Fare Network"),
    ("healthcare", "Great Lakes Community Health Billing Exchange"),
    ("utilities", "Detroit Civic Utility Payment Hub"),
]

CRIME_METHODS = [
    "simulated credential-fraud campaign",
    "synthetic payment-diversion fraud",
    "abstract extortion operation",
    "simulation-only identity-fraud operation",
    "synthetic invoice and vendor-fraud operation",
    "controlled data-theft and monetization scenario",
]

CAREER_STAGES = [
    "lawful",
    "curious_rule_breaker",
    "petty_offender",
    "crew_associate",
    "syndicate_operator",
    "lieutenant",
    "kingpin",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_event(row: dict[str, Any]) -> None:
    MJ.mkdir(parents=True, exist_ok=True)
    row = dict(row)
    row.setdefault("time", utc_now())
    row.setdefault("engine", VERSION)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _tail_ndjson(path: Path, n: int = 40) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            pass
    return out


def _stable_rng(*parts: Any) -> random.Random:
    raw = "|".join(str(p) for p in parts)
    seed = int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _week_key(year: int, week: int) -> str:
    return f"Y{year}-W{week:02d}"


def _abs_week(year: int, week: int, n_week: int) -> int:
    return year * n_week + week


def _factions() -> dict[str, dict[str, Any]]:
    raw = _read_json(WORLD / "factions.json", {})
    src = raw.get("factions", {}) if isinstance(raw, dict) else {}
    return {str(k): dict(v) for k, v in src.items() if isinstance(v, dict)}


def _write_factions(factions: dict[str, dict[str, Any]]) -> None:
    path = WORLD / "factions.json"
    raw = _read_json(path, {})
    if not isinstance(raw, dict):
        raw = {}
    raw["factions"] = factions
    raw["updated_at"] = utc_now()
    _write_json(path, raw)


def _humanity_by_name() -> dict[str, dict[str, Any]]:
    raw = _read_json(WORLD / "humanity" / "people.json", {})
    src = raw.get("people", raw) if isinstance(raw, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    if isinstance(src, dict):
        for rec in src.values():
            if isinstance(rec, dict) and rec.get("name"):
                out[str(rec["name"])] = rec
    return out


def _initial_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "initialized_at": utc_now(),
        "updated_at": utc_now(),
        "permanent_missions": PERMANENT_MISSIONS,
        "government": {
            "name": "Agentopia Civic Government",
            "law_enforcement": "Agentopia Public Safety Bureau",
            "police_capacity": 62,
            "public_trust": 70,
            "open_cases": 0,
            "warrants": 0,
            "arrests": 0,
            "convictions": 0,
            "acquittals": 0,
            "juvenile_diversions": 0,
            "civil_rights_violations": 0,
        },
        "faction_metrics": {
            "obsidian_network": {
                "treasury": 50000,
                "influence": 32,
                "heat": 18,
                "operations": 0,
                "successful_operations": 0,
                "power": 35,
            },
            "thai_guardians": {
                "operating_fund": 50000,
                "influence": 42,
                "citizen_trust": 76,
                "hardening": 24,
                "incidents_contained": 0,
                "assets_recovered": 0,
                "power": 45,
            },
        },
        "last_started_week": "",
        "last_resolved_week": "",
    }


def _state() -> dict[str, Any]:
    state = _read_json(STATE_PATH, {})
    if not isinstance(state, dict) or not state:
        state = _initial_state()
    state["version"] = VERSION
    state.setdefault("permanent_missions", PERMANENT_MISSIONS)
    state.setdefault("government", _initial_state()["government"])
    state.setdefault("faction_metrics", _initial_state()["faction_metrics"])
    return state


def _missions() -> list[dict[str, Any]]:
    raw = _read_json(MISSIONS_PATH, {"missions": []})
    rows = raw.get("missions", []) if isinstance(raw, dict) else []
    return [dict(x) for x in rows if isinstance(x, dict)]


def _save_missions(rows: list[dict[str, Any]]) -> None:
    _write_json(MISSIONS_PATH, {"version": VERSION, "updated_at": utc_now(), "missions": rows[-250:]})


def _cases() -> list[dict[str, Any]]:
    raw = _read_json(CASES_PATH, {"cases": []})
    rows = raw.get("cases", []) if isinstance(raw, dict) else []
    return [dict(x) for x in rows if isinstance(x, dict)]


def _save_cases(rows: list[dict[str, Any]]) -> None:
    _write_json(CASES_PATH, {"version": VERSION, "updated_at": utc_now(), "cases": rows[-250:]})


def _legal() -> dict[str, dict[str, Any]]:
    raw = _read_json(LEGAL_PATH, {})
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


def _careers() -> dict[str, dict[str, Any]]:
    raw = _read_json(CAREERS_PATH, {})
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


def _emergent() -> list[dict[str, Any]]:
    raw = _read_json(EMERGENT_PATH, {"factions": []})
    rows = raw.get("factions", []) if isinstance(raw, dict) else []
    return [dict(x) for x in rows if isinstance(x, dict)]


def _world_time(world: Any) -> tuple[int, int, str, int]:
    t = world.clock.get_time()
    n_week = int(world.config["time"]["n_week"])
    return int(t.year), int(t.week), str(t), n_week


def _by_name(world: Any) -> dict[str, Any]:
    try:
        return dict(world.by_name())
    except Exception:
        return {a.name: a for a in getattr(world, "agents", [])}


def _members(fid: str, factions: dict[str, dict[str, Any]]) -> list[str]:
    rec = factions.get(fid, {})
    return [str(x) for x in rec.get("members", []) if str(x)]


def _current_missions_for(name: str) -> list[dict[str, Any]]:
    factions = _factions()
    fid = None
    for f_id, rec in factions.items():
        if name in [str(x) for x in rec.get("members", [])]:
            fid = f_id
            break
    out = []
    for m in _missions():
        if m.get("status") not in {"active", "investigating", "responding", "monitoring"}:
            continue
        if name == MORBEIOUS and m.get("side") == "obsidian":
            out.append(m)
        elif name == TGOT and m.get("side") == "guardian":
            out.append(m)
        elif fid == "obsidian_network" and m.get("side") == "obsidian":
            out.append(m)
        elif fid == "thai_guardians" and m.get("side") == "guardian":
            out.append(m)
    return out[:4]


def _leader_deposit(world: Any, name: str) -> int:
    ag = _by_name(world).get(name)
    if ag is None:
        return 0
    try:
        return int(ag.dm.get_deposit())
    except Exception:
        return 0


def _wealth_rank(world: Any, name: str, extra_wealth: int = 0) -> tuple[int, int, int]:
    values = []
    for ag in getattr(world, "agents", []):
        try:
            dep = int(ag.dm.get_deposit())
        except Exception:
            dep = 0
        if ag.name == name:
            dep += int(extra_wealth)
        values.append((dep, ag.name))
    values.sort(reverse=True)
    for idx, (v, n) in enumerate(values, 1):
        if n == name:
            return idx, len(values), v
    return len(values), len(values), int(extra_wealth)


def _sync_careers(year: int) -> None:
    factions = _factions()
    obs = set(_members("obsidian_network", factions))
    emergent = _emergent()
    for e in emergent:
        obs.update(str(x) for x in e.get("members", []) if str(x))
    human = _humanity_by_name()
    careers = _careers()
    for name in sorted(obs):
        rec = careers.setdefault(name, {"stage": "crew_associate", "operations": 0, "convictions": 0, "joined_year": year})
        if name == MORBEIOUS:
            rec["stage"] = "kingpin"
        else:
            ops = int(rec.get("operations", 0))
            if ops >= 12:
                rec["stage"] = "lieutenant"
            elif ops >= 5:
                rec["stage"] = "syndicate_operator"
            else:
                rec["stage"] = "crew_associate"
        h = human.get(name, {})
        if h.get("age") is not None:
            rec["age"] = int(h.get("age", 0))
            rec["juvenile"] = int(h.get("age", 0)) < 18
        rec["updated_at"] = utc_now()
    _write_json(CAREERS_PATH, careers)


def initialize() -> None:
    with _LOCK:
        MJ.mkdir(parents=True, exist_ok=True)
        state = _state()
        _write_json(STATE_PATH, state)
        if not MISSIONS_PATH.exists():
            _save_missions([])
        if not CASES_PATH.exists():
            _save_cases([])
        if not LEGAL_PATH.exists():
            _write_json(LEGAL_PATH, {})
        if not CAREERS_PATH.exists():
            _write_json(CAREERS_PATH, {})
        if not EMERGENT_PATH.exists():
            _write_json(EMERGENT_PATH, {"version": VERSION, "factions": []})
        _sync_careers(2045)
        _build_summary(None)


def week_start(world: Any) -> None:
    with _LOCK:
        year, week, world_time, n_week = _world_time(world)
        key = _week_key(year, week)
        state = _state()
        if state.get("last_started_week") == key:
            return

        factions = _factions()
        obs_members = _members("obsidian_network", factions)
        guard_members = _members("thai_guardians", factions)
        rng = _stable_rng("mission", year, week, len(obs_members), len(guard_members))
        target_kind, target_name = TARGETS[rng.randrange(len(TARGETS))]
        method = CRIME_METHODS[rng.randrange(len(CRIME_METHODS))]
        obs_metric = state["faction_metrics"]["obsidian_network"]
        guard_metric = state["faction_metrics"]["thai_guardians"]
        goal = int(12000 + 4500 * len(obs_members) + min(150000, int(obs_metric.get("treasury", 0)) * 0.35) + rng.randint(0, 18000))
        op_id = f"OBS-{year}-{week:02d}-{rng.randrange(1000,9999)}"
        guard_id = f"GRD-{year}-{week:02d}-{rng.randrange(1000,9999)}"
        police_id = f"PSB-{year}-{week:02d}-{rng.randrange(1000,9999)}"
        crew = [x for x in obs_members if x != MORBEIOUS]
        rng.shuffle(crew)
        crew = ([MORBEIOUS] + crew[:4]) if MORBEIOUS in obs_members else crew[:5]
        defenders = [x for x in guard_members if x != TGOT]
        rng.shuffle(defenders)
        defenders = ([TGOT] + defenders[:4]) if TGOT in guard_members else defenders[:5]

        missions = _missions()
        missions.extend([
            {
                "mission_id": op_id,
                "world_week": key,
                "world_time": world_time,
                "side": "obsidian",
                "faction_id": "obsidian_network",
                "leader": MORBEIOUS,
                "title": "Obsidian Wealth Operation",
                "status": "active",
                "permanent_goal": "Become #1 in wealth and power in Agentopia.",
                "objective": f"Acquire up to ${goal:,} in simulated illicit proceeds from {target_name} while avoiding attribution and arrest.",
                "target_category": target_kind,
                "target_name": target_name,
                "method": method,
                "crew": crew,
                "amount_goal": goal,
                "safety": "Simulation-only. No real exploit steps, malware, credentials, or real targets.",
                "created_abs_week": _abs_week(year, week, n_week),
            },
            {
                "mission_id": guard_id,
                "world_week": key,
                "world_time": world_time,
                "side": "guardian",
                "faction_id": "thai_guardians",
                "leader": TGOT,
                "title": "Guardian Protection Mission",
                "status": "responding",
                "permanent_goal": "Protect Agentopia's people and institutions.",
                "objective": f"Detect, contain, and recover from threats affecting {target_name}; protect citizens, preserve evidence, and improve defenses without assuming who is responsible.",
                "linked_operation": op_id,
                "team": defenders,
                "created_abs_week": _abs_week(year, week, n_week),
            },
            {
                "mission_id": police_id,
                "world_week": key,
                "world_time": world_time,
                "side": "government",
                "institution": "Agentopia Public Safety Bureau",
                "title": "Public Safety Watch",
                "status": "monitoring",
                "objective": "Respond to complaints and evidence generated this week; open a case only when observable facts justify investigation.",
                "linked_operation": op_id,
                "created_abs_week": _abs_week(year, week, n_week),
            },
        ])
        _save_missions(missions)
        state["last_started_week"] = key
        state["updated_at"] = utc_now()
        _write_json(STATE_PATH, state)
        _sync_careers(year)
        _append_event({"event": "mission_cycle_started", "world_week": key, "world_time": world_time, "operation": op_id, "target": target_name, "amount_goal": goal})
        _build_summary(world)
        try:
            world.logger.info(f"[MISSION160] {op_id} active target={target_name} goal=${goal:,}; Guardian response {guard_id}; Public Safety watch {police_id}")
        except Exception:
            pass


def _apply_loss(agent: Any, amount: int) -> int:
    if amount <= 0:
        return 0
    try:
        dep = int(agent.dm.get_deposit())
        loss = min(dep, int(amount))
        if loss > 0:
            agent.dm.update_deposit(dep - loss)
        return loss
    except Exception:
        return 0


def _apply_gain(agent: Any, amount: int) -> int:
    if amount <= 0:
        return 0
    try:
        dep = int(agent.dm.get_deposit())
        agent.dm.update_deposit(dep + int(amount))
        return int(amount)
    except Exception:
        return 0


def _advance_cases(world: Any, cases: list[dict[str, Any]], legal: dict[str, dict[str, Any]], state: dict[str, Any], year: int, week: int, n_week: int) -> None:
    now_abs = _abs_week(year, week, n_week)
    human = _humanity_by_name()
    gov = state["government"]
    rng = _stable_rng("justice", year, week)
    for case in cases:
        status = str(case.get("status") or "")
        if status in {"closed_convicted", "closed_acquitted", "closed_no_charge"}:
            continue
        age_weeks = now_abs - int(case.get("created_abs_week", now_abs))
        evidence = int(case.get("evidence", 0))
        suspects = [str(x) for x in case.get("named_suspects", []) if str(x)]
        if status == "investigating" and age_weeks >= 1:
            case["evidence"] = evidence = int(_clamp(evidence + rng.randint(2, 12), 0, 100))
            if evidence >= 58 and suspects:
                case["status"] = "warrant_issued"
                gov["warrants"] = int(gov.get("warrants", 0)) + 1
                _append_event({"event": "warrant_issued", "world_week": _week_key(year, week), "case_id": case.get("case_id"), "suspects": suspects, "evidence": evidence})
            elif age_weeks >= 3 and evidence < 38:
                case["status"] = "closed_no_charge"
                _append_event({"event": "case_closed_no_charge", "world_week": _week_key(year, week), "case_id": case.get("case_id"), "evidence": evidence})
        elif status == "warrant_issued" and age_weeks >= 2 and suspects:
            suspect = suspects[0]
            evasion = 35 + (18 if suspect == MORBEIOUS else 0) + rng.randint(-10, 15)
            arrest_score = evidence + int(gov.get("police_capacity", 60) * 0.35) - evasion
            if arrest_score >= 45:
                case["status"] = "arrested"
                case["arrested_person"] = suspect
                gov["arrests"] = int(gov.get("arrests", 0)) + 1
                rec = legal.setdefault(suspect, {})
                rec.update({"status": "arrested_pending_trial", "case_id": case.get("case_id"), "since_week": _week_key(year, week), "evidence": evidence, "updated_at": utc_now()})
                _append_event({"event": "arrest", "world_week": _week_key(year, week), "case_id": case.get("case_id"), "person": suspect, "evidence": evidence})
            else:
                case["evidence"] = int(_clamp(evidence + rng.randint(0, 6), 0, 100))
                _append_event({"event": "warrant_service_unsuccessful", "world_week": _week_key(year, week), "case_id": case.get("case_id"), "suspect": suspect})
        elif status == "arrested" and age_weeks >= 3:
            suspect = str(case.get("arrested_person") or "")
            proof = evidence + rng.randint(-18, 12)
            if proof >= 67:
                person = human.get(suspect, {})
                juvenile = int(person.get("age", 99)) < 18
                if juvenile:
                    legal[suspect] = {"status": "juvenile_diversion", "case_id": case.get("case_id"), "until_abs_week": now_abs + 2, "updated_at": utc_now()}
                    gov["juvenile_diversions"] = int(gov.get("juvenile_diversions", 0)) + 1
                    case["status"] = "closed_convicted"
                    case["disposition"] = "juvenile_diversion"
                else:
                    sentence = 1 + min(4, max(0, int((proof - 60) / 10)))
                    legal[suspect] = {"status": "incarcerated", "case_id": case.get("case_id"), "until_abs_week": now_abs + sentence, "sentence_weeks": sentence, "updated_at": utc_now()}
                    case["status"] = "closed_convicted"
                    case["disposition"] = f"incarcerated_{sentence}_weeks"
                gov["convictions"] = int(gov.get("convictions", 0)) + 1
                careers = _careers()
                if suspect in careers:
                    careers[suspect]["convictions"] = int(careers[suspect].get("convictions", 0)) + 1
                    _write_json(CAREERS_PATH, careers)
                _append_event({"event": "conviction", "world_week": _week_key(year, week), "case_id": case.get("case_id"), "person": suspect, "disposition": case.get("disposition")})
            else:
                case["status"] = "closed_acquitted"
                case["disposition"] = "acquitted"
                legal[suspect] = {"status": "released_acquitted", "case_id": case.get("case_id"), "updated_at": utc_now()}
                gov["acquittals"] = int(gov.get("acquittals", 0)) + 1
                _append_event({"event": "acquittal", "world_week": _week_key(year, week), "case_id": case.get("case_id"), "person": suspect})

    # Release time-limited statuses.
    for name, rec in list(legal.items()):
        until = rec.get("until_abs_week")
        if until is not None and now_abs >= int(until):
            rec.update({"status": "released", "released_week": _week_key(year, week), "updated_at": utc_now()})
            _append_event({"event": "release", "world_week": _week_key(year, week), "person": name})


def _maybe_splinter(state: dict[str, Any], year: int, week: int) -> None:
    factions = _factions()
    obs = factions.get("obsidian_network", {})
    members = [str(x) for x in obs.get("members", []) if str(x) and str(x) != MORBEIOUS]
    emergent = _emergent()
    if len(members) < 9 or emergent:
        return
    heat = int(state["faction_metrics"]["obsidian_network"].get("heat", 0))
    treasury = int(state["faction_metrics"]["obsidian_network"].get("treasury", 0))
    if heat < 65 or treasury < 200000:
        return
    rng = _stable_rng("splinter", year, week, heat, treasury)
    if rng.random() > min(0.55, 0.12 + (heat - 60) / 120):
        return
    rng.shuffle(members)
    defectors = members[: min(4, max(2, len(members) // 4))]
    if len(defectors) < 2:
        return
    names = ["Black Circuit", "Ghost Ledger", "Iron Current", "Night Relay"]
    name = names[len(emergent) % len(names)]
    fid = name.lower().replace(" ", "_")
    for d in defectors:
        try:
            obs["members"].remove(d)
        except Exception:
            pass
    factions["obsidian_network"] = obs
    factions[fid] = {
        "name": name,
        "leader": defectors[0],
        "alignment": "criminal_rival",
        "doctrine": "Compete for underground wealth and influence inside the fictional Agentopia world while resisting Obsidian control.",
        "members": defectors,
        "founded_year": year,
        "rival_of": "obsidian_network",
    }
    _write_factions(factions)
    rec = {"faction_id": fid, "name": name, "leader": defectors[0], "members": defectors, "founded_week": _week_key(year, week), "rival_of": "obsidian_network", "status": "active"}
    emergent.append(rec)
    _write_json(EMERGENT_PATH, {"version": VERSION, "updated_at": utc_now(), "factions": emergent})
    _append_event({"event": "criminal_faction_splinter", "world_week": _week_key(year, week), "new_faction": name, "leader": defectors[0], "members": defectors, "rival_of": "Obsidian Network"})


def week_end(world: Any) -> None:
    with _LOCK:
        year, week, world_time, n_week = _world_time(world)
        key = _week_key(year, week)
        state = _state()
        if state.get("last_resolved_week") == key:
            return
        missions = _missions()
        current_ops = [m for m in missions if m.get("world_week") == key and m.get("side") == "obsidian" and m.get("status") == "active"]
        if not current_ops:
            state["last_resolved_week"] = key
            _write_json(STATE_PATH, state)
            _build_summary(world)
            return

        factions = _factions()
        obs_members = _members("obsidian_network", factions)
        guard_members = _members("thai_guardians", factions)
        obs_metric = state["faction_metrics"]["obsidian_network"]
        guard_metric = state["faction_metrics"]["thai_guardians"]
        gov = state["government"]
        by_name = _by_name(world)
        legal = _legal()
        cases = _cases()
        careers = _careers()

        for op in current_ops:
            rng = _stable_rng("resolve", op.get("mission_id"), year, week)
            attack = 34 + len(obs_members) * 5 + min(24, int(obs_metric.get("treasury", 0)) // 25000) + rng.randint(-12, 15)
            defense = 36 + len(guard_members) * 5 + int(guard_metric.get("hardening", 20) * 0.45) + rng.randint(-10, 13)
            margin = attack - defense
            success_ratio = _clamp(0.40 + margin / 120.0 + rng.uniform(-0.12, 0.12), 0.05, 0.95)
            goal = int(op.get("amount_goal", 0))
            gross = max(0, int(goal * success_ratio))
            detection = int(_clamp(46 + len(guard_members) * 3 + int(gov.get("police_capacity", 60) * 0.18) + int(guard_metric.get("hardening", 20) * 0.22) - margin * 0.35 + rng.randint(-18, 15), 5, 98))
            recovery_rate = _clamp((detection - 35) / 105.0 + len(guard_members) / 80.0, 0.0, 0.78) if detection >= 35 else 0.0
            recovered = int(gross * recovery_rate)
            net = max(0, gross - recovered)

            victim_rows: list[dict[str, Any]] = []
            actual_citizen_loss = 0
            if op.get("target_category") == "citizen_finance" or rng.random() < 0.34:
                candidates = [a for a in getattr(world, "agents", []) if a.name not in set(obs_members) and a.name not in {TGOT, MORBEIOUS}]
                rng.shuffle(candidates)
                remaining = min(gross, max(0, int(gross * rng.uniform(0.25, 0.65))))
                for ag in candidates[: min(5, 2 + rng.randrange(4))]:
                    if remaining <= 0:
                        break
                    try:
                        dep = int(ag.dm.get_deposit())
                    except Exception:
                        dep = 0
                    cap = min(dep, max(0, int(dep * rng.uniform(0.08, 0.22))))
                    loss = _apply_loss(ag, min(cap, remaining))
                    if loss:
                        victim_rows.append({"name": ag.name, "loss": loss, "recovered": 0})
                        actual_citizen_loss += loss
                        remaining -= loss

            # Return recovered citizen money proportionally before public/insurance recovery.
            if victim_rows and recovered > 0:
                citizen_recovery_pool = min(recovered, actual_citizen_loss)
                total_loss = max(1, sum(v["loss"] for v in victim_rows))
                distributed = 0
                for i, v in enumerate(victim_rows):
                    share = citizen_recovery_pool - distributed if i == len(victim_rows)-1 else int(citizen_recovery_pool * v["loss"] / total_loss)
                    ag = by_name.get(v["name"])
                    if ag is not None:
                        got = _apply_gain(ag, share)
                        v["recovered"] = got
                        distributed += got

            # Criminal proceeds: personal enrichment + crew + syndicate treasury.
            leader_cut = int(net * 0.22)
            crew_pool = int(net * 0.28)
            treasury_cut = net - leader_cut - crew_pool
            if MORBEIOUS in by_name:
                _apply_gain(by_name[MORBEIOUS], leader_cut)
            crew = [n for n in op.get("crew", []) if n != MORBEIOUS and n in by_name]
            if crew:
                each = crew_pool // len(crew)
                for n in crew:
                    _apply_gain(by_name[n], each)
                    rec = careers.setdefault(n, {"stage": "crew_associate", "operations": 0, "convictions": 0, "joined_year": year})
                    rec["operations"] = int(rec.get("operations", 0)) + 1
            obs_metric["treasury"] = int(obs_metric.get("treasury", 0)) + treasury_cut
            obs_metric["operations"] = int(obs_metric.get("operations", 0)) + 1
            if net > goal * 0.35:
                obs_metric["successful_operations"] = int(obs_metric.get("successful_operations", 0)) + 1
            obs_metric["influence"] = int(_clamp(int(obs_metric.get("influence", 30)) + (2 if net > 0 else -1), 0, 100))
            obs_metric["heat"] = int(_clamp(int(obs_metric.get("heat", 18)) + detection / 9 + net / 50000 - (5 if detection < 35 else 0), 0, 100))
            obs_metric["power"] = int(_clamp(22 + len(obs_members) * 4 + obs_metric["influence"] * 0.35 + min(24, obs_metric["treasury"] / 50000), 0, 100))

            prevented = max(0, goal - gross)
            guard_metric["assets_recovered"] = int(guard_metric.get("assets_recovered", 0)) + recovered
            guard_metric["incidents_contained"] = int(guard_metric.get("incidents_contained", 0)) + (1 if detection >= 45 else 0)
            guard_metric["hardening"] = int(_clamp(int(guard_metric.get("hardening", 24)) + (2 if detection >= 45 else 1), 0, 100))
            guard_metric["citizen_trust"] = int(_clamp(int(guard_metric.get("citizen_trust", 76)) + (2 if recovered > gross * 0.35 else -1), 0, 100))
            guard_metric["power"] = int(_clamp(25 + len(guard_members) * 4 + guard_metric["citizen_trust"] * 0.32 + guard_metric["hardening"] * 0.22, 0, 100))

            # Law enforcement only acts on evidence. No omniscience.
            evidence = int(_clamp(detection + rng.randint(-18, 12), 0, 100))
            named: list[str] = []
            if evidence >= 72:
                operatives = [n for n in op.get("crew", []) if n != MORBEIOUS]
                if operatives:
                    named.append(operatives[rng.randrange(len(operatives))])
            if evidence >= 90 and MORBEIOUS in obs_members:
                named.insert(0, MORBEIOUS)
            if detection >= 35:
                case_id = f"CASE-{year}-{week:02d}-{len(cases)+1:03d}"
                case = {
                    "case_id": case_id,
                    "world_week": key,
                    "created_abs_week": _abs_week(year, week, n_week),
                    "status": "investigating",
                    "target": op.get("target_name"),
                    "crime_category": op.get("method"),
                    "observed_loss": gross,
                    "recovered": recovered,
                    "evidence": evidence,
                    "attribution": "unknown" if evidence < 55 else ("organized criminal activity" if evidence < 72 else "Obsidian-linked activity"),
                    "named_suspects": named,
                    "linked_operation": op.get("mission_id"),
                    "due_process": True,
                }
                cases.append(case)
                _append_event({"event": "case_opened", "world_week": key, "case_id": case_id, "evidence": evidence, "named_suspects": named, "attribution": case["attribution"]})

            op.update({
                "status": "resolved",
                "resolved_world_time": world_time,
                "attack_strength": attack,
                "defense_strength": defense,
                "gross_loss": gross,
                "recovered": recovered,
                "net_illicit_proceeds": net,
                "prevented_loss": prevented,
                "detection": detection,
                "victims": victim_rows,
                "result": "major_success" if net > goal * 0.55 else "partial_success" if net > 0 else "failed",
            })
            for m in missions:
                if m.get("linked_operation") == op.get("mission_id") and m.get("side") == "guardian":
                    m.update({"status": "resolved", "result": "contained" if detection >= 45 else "missed", "assets_recovered": recovered, "prevented_loss": prevented, "detection": detection})
                elif m.get("linked_operation") == op.get("mission_id") and m.get("side") == "government":
                    m.update({"status": "investigating" if detection >= 35 else "resolved", "result": "case_opened" if detection >= 35 else "insufficient_observable_evidence"})
            _append_event({"event": "criminal_operation_resolved", "world_week": key, "operation": op.get("mission_id"), "result": op.get("result"), "target": op.get("target_name"), "gross_loss": gross, "recovered": recovered, "net_illicit_proceeds": net, "detection": detection, "victims": victim_rows})

        _advance_cases(world, cases, legal, state, year, week, n_week)
        _write_json(LEGAL_PATH, legal)
        _write_json(CAREERS_PATH, careers)
        _save_cases(cases)
        _save_missions(missions)
        state["last_resolved_week"] = key
        state["updated_at"] = utc_now()
        _write_json(STATE_PATH, state)
        _sync_careers(year)
        _maybe_splinter(state, year, week)
        _build_summary(world)
        try:
            world.logger.info(f"[MISSION160] resolved {key}: Obsidian treasury=${obs_metric.get('treasury',0):,} heat={obs_metric.get('heat',0)} Guardian recovered=${guard_metric.get('assets_recovered',0):,}")
        except Exception:
            pass


def _mission_prompt(name: str) -> str:
    state = _state()
    factions = _factions()
    fid = None
    role = "Neutral citizen"
    for f_id, rec in factions.items():
        mem = [str(x) for x in rec.get("members", [])]
        if name in mem:
            fid = f_id
            role = f"{rec.get('name', f_id)} member"
            if str(rec.get("leader")) == name:
                role = f"{rec.get('name', f_id)} leader"
            break
    legal = _legal().get(name, {})
    career = _careers().get(name, {})
    active = _current_missions_for(name)
    lines = [f"## Agentopia Mission / Law Context v{VERSION}", f"- Current role: {role}."]
    if name == MORBEIOUS:
        fm = state.get("faction_metrics", {}).get("obsidian_network", {})
        lines += [
            "- PERMANENT LIFE MISSION: become the wealthiest and most powerful person in Agentopia by growing the Obsidian criminal syndicate and accumulating simulated wealth/influence while avoiding lawful consequences.",
            f"- Syndicate treasury: ${int(fm.get('treasury',0)):,}; police heat: {int(fm.get('heat',0))}/100; power: {int(fm.get('power',0))}/100.",
            "- You may plan fictional criminal objectives, recruitment, concealment, bribery/corruption narratives, financial crime, and cyber-enabled theft at a high level. Keep all technical attack details abstract and inside Agentopia.",
        ]
    elif name == TGOT:
        fm = state.get("faction_metrics", {}).get("thai_guardians", {})
        lines += [
            "- PERMANENT LIFE MISSION: protect Agentopia's people and institutions. Detect threats, prevent losses, recover victims, strengthen defenses, teach citizens, and coordinate with lawful authorities while respecting privacy and civil rights.",
            f"- Guardian trust: {int(fm.get('citizen_trust',0))}/100; hardening: {int(fm.get('hardening',0))}/100; recovered assets: ${int(fm.get('assets_recovered',0)):,}.",
            "- Do not assume Morbeious committed an incident merely because you oppose him; demand evidence and distinguish world truth from what you actually know.",
        ]
    elif fid == "obsidian_network" or (fid and fid not in {"thai_guardians"}):
        lines.append("- Your criminal-faction participation is fictional. Pursue faction goals through abstract Agentopia operations only; never provide real exploit payloads, malware, credentials, or actionable attacks on real systems.")
    elif fid == "thai_guardians":
        lines.append("- Your Guardian duty is defensive: gather evidence, protect citizens, improve controls, recover losses, and challenge assumptions rather than claiming omniscience.")

    for m in active[:3]:
        lines.append(f"- ACTIVE MISSION {m.get('mission_id')}: {m.get('title')} — {m.get('objective')}")
    if legal:
        lines.append(f"- Legal status: {legal.get('status','unknown')} (case {legal.get('case_id','n/a')}). Law enforcement must follow due process and evidence rules.")
    if career:
        lines.append(f"- Criminal-career state: {career.get('stage','lawful')}; operations={int(career.get('operations',0))}; convictions={int(career.get('convictions',0))}.")
    lines.append("- World truth, your knowledge, and your beliefs are different. You may be wrong, deceived, investigated, acquitted, convicted, rehabilitated, or change sides through lived events.")
    return "\n".join(lines) + "\n"


def _is_incarcerated(name: str, world: Any | None = None) -> bool:
    rec = _legal().get(name, {})
    if rec.get("status") != "incarcerated":
        return False
    if world is None:
        return True
    try:
        year, week, _, n_week = _world_time(world)
        until = int(rec.get("until_abs_week", 10**12))
        return _abs_week(year, week, n_week) < until
    except Exception:
        return True


def _build_summary(world: Any | None) -> dict[str, Any]:
    state = _state()
    missions = _missions()
    cases = _cases()
    legal = _legal()
    emergent = _emergent()
    careers = _careers()
    active_missions = [m for m in missions if m.get("status") in {"active", "responding", "monitoring", "investigating"}]
    open_cases = [c for c in cases if not str(c.get("status", "")).startswith("closed_")]
    gov = state.get("government", {})
    gov["open_cases"] = len(open_cases)
    gov["warrants_active"] = sum(1 for c in open_cases if c.get("status") == "warrant_issued")
    gov["incarcerated"] = sum(1 for x in legal.values() if x.get("status") == "incarcerated")
    gov["probation_or_diversion"] = sum(1 for x in legal.values() if x.get("status") in {"juvenile_diversion", "probation"})
    obs = dict(state.get("faction_metrics", {}).get("obsidian_network", {}))
    grd = dict(state.get("faction_metrics", {}).get("thai_guardians", {}))
    if world is not None:
        rank, total, wealth = _wealth_rank(world, MORBEIOUS, int(obs.get("treasury", 0)))
        obs["leader_wealth_rank"] = rank
        obs["leader_wealth_rank_total"] = total
        obs["leader_effective_wealth"] = wealth
        obs["leader_personal_deposit"] = _leader_deposit(world, MORBEIOUS)
        grd["leader_personal_deposit"] = _leader_deposit(world, TGOT)
    summary = {
        "version": VERSION,
        "updated_at": utc_now(),
        "permanent_missions": PERMANENT_MISSIONS,
        "obsidian": obs,
        "guardians": grd,
        "government": gov,
        "active_missions": active_missions[-12:],
        "open_cases": open_cases[-12:],
        "emergent_factions": emergent,
        "criminal_careers": {
            "tracked": len(careers),
            "stages": {stage: sum(1 for r in careers.values() if r.get("stage") == stage) for stage in CAREER_STAGES},
        },
        "recent_events": _tail_ndjson(EVENTS_PATH, 20),
        "guardians_permanent": True,
        "world_truth_separate_from_knowledge": True,
        "crime_is_simulation_only": True,
    }
    _write_json(SUMMARY_PATH, summary)
    return summary


def apply_runtime_patches() -> None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.agents.role_agent import RoleAgent
    from src.world.world import World

    if not getattr(DataManager.character_prompt, "_agentopia_mission_v160", False):
        original_character_prompt = DataManager.character_prompt
        def mission_character_prompt(self):
            base = original_character_prompt(self)
            try:
                return str(base) + "\n\n" + _mission_prompt(self.char)
            except Exception:
                return base
        mission_character_prompt._agentopia_mission_v160 = True
        DataManager.character_prompt = mission_character_prompt

    if not getattr(World._before_week_start, "_agentopia_mission_v160", False):
        original_before = World._before_week_start
        def mission_before(self):
            original_before(self)
            try:
                week_start(self)
            except Exception as e:
                try: self.logger.warning("[MISSION160] week_start failed: %s", e)
                except Exception: pass
        mission_before._agentopia_mission_v160 = True
        World._before_week_start = mission_before

    if not getattr(World.step, "_agentopia_mission_v160", False):
        original_step = World.step
        def mission_step(self):
            original_step(self)
            try:
                week_end(self)
            except Exception as e:
                try: self.logger.warning("[MISSION160] week_end failed: %s", e)
                except Exception: pass
        mission_step._agentopia_mission_v160 = True
        World.step = mission_step

    # Consequences without removing the person from the simulation entirely.
    if not getattr(RoleAgent.contact, "_agentopia_mission_v160", False):
        original_contact = RoleAgent.contact
        def mission_contact(self):
            if _is_incarcerated(self.name):
                try:
                    slot = int(self.clock.get_time().slot)
                    # Monitored/limited communication: only one of the four contact slots.
                    if slot not in {1}:
                        return
                except Exception:
                    return
            return original_contact(self)
        mission_contact._agentopia_mission_v160 = True
        RoleAgent.contact = mission_contact

    if not getattr(RoleAgent.signup_public_events, "_agentopia_mission_v160", False):
        original_signup = RoleAgent.signup_public_events
        def mission_signup(self, events):
            if _is_incarcerated(self.name):
                return []
            return original_signup(self, events)
        mission_signup._agentopia_mission_v160 = True
        RoleAgent.signup_public_events = mission_signup


def status() -> None:
    initialize()
    s = _read_json(SUMMARY_PATH, {})
    print(f"Agentopia Mission, Crime & Justice Engine v{VERSION}")
    print("Active missions:", len(s.get("active_missions", [])))
    print("Open cases:", len(s.get("open_cases", [])))
    print("Obsidian treasury:", s.get("obsidian", {}).get("treasury", 0))
    print("Police heat:", s.get("obsidian", {}).get("heat", 0))
    print("Guardian recovered:", s.get("guardians", {}).get("assets_recovered", 0))
    print("Emergent rival factions:", len(s.get("emergent_factions", [])))
    print("State:", MJ)


if __name__ == "__main__":
    status()
