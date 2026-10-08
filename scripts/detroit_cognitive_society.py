#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
COG = WORLD / "cognition"
DT = WORLD / "digital_twin"
VERSION = "1.3.0"

STOPWORDS = {
    "the","and","for","that","with","this","from","into","their","they","them","his","her","she","him","our","your","you","are","was","were","will","would","could","should","about","over","under","through","while","where","when","what","which","who","why","how","have","has","had","not","but","out","all","any","can","its","it's","than","then","too","very","being","been","because","against","without","within","between","before","after","each","more","most","some","such","only","own","same","other","another","people","person"
}

BASE_CULTURE = {
    "Detroit resilience": 0.86,
    "maker and mobility culture": 0.78,
    "neighborhood loyalty": 0.76,
    "music and creative identity": 0.74,
    "community self-determination": 0.72,
    "digital sovereignty": 0.70,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_ndjson(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_ndjson(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def health(port: int) -> bool:
    for endpoint in ("/health", "/v1/models"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{endpoint}", timeout=0.35) as r:
                if 200 <= r.status < 500:
                    return True
        except Exception:
            pass
    return False


def profile_files(person_dir: Path) -> list[Path]:
    base = person_dir / "profile"
    if not base.exists():
        return []
    def key(p: Path) -> tuple[int, str]:
        m = re.search(r"year=(\d+)", p.name)
        return (int(m.group(1)) if m else -1, p.name)
    return sorted(base.glob("year=*.json"), key=key)


def active_names() -> set[str]:
    view = WORLD / ".active_persona_view"
    if view.exists():
        return {p.name for p in view.iterdir() if p.is_dir() or p.is_symlink()}
    root = WORLD / "persona"
    if not root.exists():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and not (p / "_background.json").exists()}


def population_names() -> list[str]:
    root = WORLD / "persona"
    if not root.exists():
        return []
    return sorted((p.name for p in root.iterdir() if p.is_dir()), key=str.casefold)


def token_set(text: Any) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", str(text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def faction_index() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    raw = read_json(WORLD / "factions.json", {})
    factions: dict[str, dict[str, Any]] = {}
    member_to_faction: dict[str, str] = {}
    source = raw.get("factions") if isinstance(raw, dict) and isinstance(raw.get("factions"), dict) else raw
    if isinstance(source, dict):
        for key, value in source.items():
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or key)
            members = [str(x) for x in value.get("members", []) if str(x).strip()]
            leader = str(value.get("leader") or "")
            if leader and leader not in members:
                members.insert(0, leader)
            rec = dict(value)
            rec["name"] = name
            rec["members"] = members
            factions[name] = rec
            for m in members:
                member_to_faction[m] = name
    return factions, member_to_faction


def contact_summary(name: str, limit: int = 12) -> list[dict[str, Any]]:
    root = WORLD / "persona" / name / "contact"
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for p in root.glob("*.jsonl"):
        if p.name == "sig.jsonl":
            continue
        count = 0
        last_time = None
        peer = p.stem
        try:
            for raw in p.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]:
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                count += 1
                last_time = obj.get("time") or last_time
                frm = str(obj.get("from") or "")
                if frm and frm != name:
                    peer = frm
        except Exception:
            continue
        if count:
            rows.append({"person": peer, "observed_messages": count, "last_time": last_time})
    rows.sort(key=lambda x: (x["observed_messages"], str(x.get("last_time") or "")), reverse=True)
    return rows[:limit]


def ensure_baselines(names: list[str]) -> dict[str, Any]:
    path = COG / "persona_baselines.json"
    baselines = read_json(path, {})
    if not isinstance(baselines, dict):
        baselines = {}
    root = WORLD / "persona"
    changed = False
    for name in names:
        if name in baselines:
            continue
        files = profile_files(root / name)
        if not files:
            continue
        profile = read_json(files[0], {})
        if not isinstance(profile, dict):
            continue
        baselines[name] = {
            "source": files[0].name,
            "captured_at": now(),
            "personality": ((profile.get("personality_traits") or {}).get("quantitative") or {}),
            "values": profile.get("values", ""),
            "core_motivation": profile.get("core_motivation", ""),
            "preferences": profile.get("preferences", ""),
            "brief_introduction": profile.get("brief_introduction", ""),
        }
        changed = True
    if changed or not path.exists():
        write_json(path, baselines)
    return baselines


def drift_report(names: list[str], baselines: dict[str, Any]) -> dict[str, Any]:
    root = WORLD / "persona"
    agents: dict[str, Any] = {}
    counts = Counter()
    for name in names:
        base = baselines.get(name)
        files = profile_files(root / name)
        if not isinstance(base, dict) or not files:
            continue
        cur = read_json(files[-1], {})
        if not isinstance(cur, dict):
            continue
        bq = base.get("personality") if isinstance(base.get("personality"), dict) else {}
        cq = ((cur.get("personality_traits") or {}).get("quantitative") or {})
        shared = sorted(set(bq) & set(cq))
        numeric = sum(abs(float(bq[k]) - float(cq[k])) / 100.0 for k in shared) / len(shared) if shared else 0.0
        bt = token_set(" ".join(str(base.get(k, "")) for k in ("values", "core_motivation", "preferences")))
        ct = token_set(" ".join(str(cur.get(k, "")) for k in ("values", "core_motivation", "preferences")))
        text_loss = 1.0 - jaccard(bt, ct)
        score = round(min(1.0, 0.70 * numeric + 0.30 * text_loss), 3)
        status = "stable" if score < 0.20 else ("watch" if score < 0.35 else "high")
        counts[status] += 1
        agents[name] = {
            "score": score,
            "status": status,
            "baseline_profile": base.get("source"),
            "current_profile": files[-1].name,
            "numeric_drift": round(numeric, 3),
            "identity_anchor_loss": round(text_loss, 3),
        }
    report = {"version": VERSION, "updated_at": now(), "counts": dict(counts), "agents": agents}
    write_json(COG / "drift_report.json", report)
    return report


def recent_cyber_events() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return read_ndjson(DT / "cyber_events.jsonl", 40), read_ndjson(DT / "audit_events.jsonl", 40)


def build_truth(names: list[str], factions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cp = read_json(WORLD / "checkpoint.json", {})
    dt_state = read_json(DT / "state.json", {})
    infra_state = read_json(DT / "infrastructure_state.json", {})
    vuln_counts: dict[str, int] = {}
    if isinstance(infra_state, dict):
        for key, rec in infra_state.items():
            if isinstance(rec, dict):
                vuln_counts[str(key)] = len(rec.get("open_vulnerabilities") or [])
    truth = {
        "version": VERSION,
        "updated_at": now(),
        "checkpoint": cp,
        "population": len(names),
        "factions": {k: {"leader": v.get("leader"), "members": len(v.get("members") or [])} for k, v in factions.items()},
        "digital_twin": {
            "resilience": dt_state.get("resilience"),
            "campaigns": dt_state.get("campaigns"),
            "successful_simulated_incidents": dt_state.get("successful"),
            "hidden_open_vulnerability_counts": vuln_counts,
        },
        "rule": "World truth is system-only. Citizens receive limited belief state, never this complete object.",
    }
    write_json(COG / "world_truth.json", truth)
    return truth


def build_institutions(factions: dict[str, dict[str, Any]], cyber: list[dict[str, Any]], audits: list[dict[str, Any]]) -> dict[str, Any]:
    existing = read_json(COG / "institutions.json", {})
    if not isinstance(existing, dict):
        existing = {}
    institutions = existing.get("institutions") if isinstance(existing.get("institutions"), dict) else {}
    seeds = {
        "Detroit Civic Core": {"type": "civic", "mission": "Maintain a functioning, resilient Detroit society."},
        "Detroit Infrastructure Council": {"type": "infrastructure", "mission": "Coordinate resilience across synthetic IT/OT sectors."},
    }
    for name, rec in factions.items():
        seeds[name] = {"type": "faction", "mission": str(rec.get("doctrine") or rec.get("mission") or "Persistent faction memory")}
    for name, seed in seeds.items():
        institutions.setdefault(name, {**seed, "memory": []})
    seen = {m.get("id") for inst in institutions.values() if isinstance(inst, dict) for m in (inst.get("memory") or []) if isinstance(m, dict)}
    def add(inst_name: str, source: dict[str, Any], kind: str, summary: str) -> None:
        inst = institutions.setdefault(inst_name, {"type": "institution", "mission": "Persistent institutional memory", "memory": []})
        mem = inst.setdefault("memory", [])
        raw = json.dumps(source, sort_keys=True, default=str)
        mid = hashlib.sha256((kind + raw).encode()).hexdigest()[:16]
        if mid in seen:
            return
        seen.add(mid)
        mem.append({"id": mid, "time": source.get("time"), "kind": kind, "summary": summary[:420]})
        del mem[:-200]
    for e in cyber[-30:]:
        target = str(e.get("target") or "Detroit infrastructure")
        threat = str(e.get("threat") or "cyber campaign").replace("_", " ")
        result = str(e.get("result") or "unknown")
        add("Obsidian Network", e, "operation", f"Operation against {target}: {threat}; result={result}; detected={bool(e.get('detected'))}.")
        add("ThAI Guardians", e, "threat_intelligence", f"Observed {threat} targeting {target}; result={result}; detection={bool(e.get('detected'))}.")
        add("Detroit Infrastructure Council", e, "incident", f"Synthetic {threat} activity affected or tested {target}; outcome={result}.")
    for a in audits[-30:]:
        target = str(a.get("target") or "Detroit infrastructure")
        improved = ", ".join(str(x) for x in (a.get("improved_controls") or []))
        add("ThAI Guardians", a, "purple_review", f"Purple-team review of {target}; improved controls: {improved or 'documented'}.")
        add("Detroit Infrastructure Council", a, "resilience", f"Defensive review of {target}; controls improved: {improved or 'documented'}.")
    out = {"version": VERSION, "updated_at": now(), "institutions": institutions}
    write_json(COG / "institutions.json", out)
    return out


def build_culture(dt_state: dict[str, Any], factions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    signals = dict(BASE_CULTURE)
    campaigns = float(dt_state.get("campaigns") or 0)
    success = float(dt_state.get("successful") or 0)
    signals["cyber vigilance"] = min(1.0, 0.52 + campaigns * 0.008)
    signals["recovery discipline"] = min(1.0, 0.50 + success * 0.01)
    subcultures = {
        "ThAI Guardians": ["evidence over opinion", "defense in depth", "audit and receipts", "human accountability"],
        "Obsidian Network": ["secrecy", "information advantage", "adaptation", "control through knowledge"],
    }
    for name in factions:
        subcultures.setdefault(name, ["faction loyalty", "shared institutional memory"])
    out = {
        "version": VERSION,
        "updated_at": now(),
        "city_signals": [{"signal": k, "strength": round(v, 3)} for k, v in sorted(signals.items(), key=lambda kv: kv[1], reverse=True)],
        "subcultures": subcultures,
        "principle": "Culture influences agents but does not overwrite individual personality or memory.",
    }
    write_json(COG / "culture.json", out)
    return out


def build_beliefs(names: list[str], active: set[str], member_to_faction: dict[str, str], cyber: list[dict[str, Any]], audits: list[dict[str, Any]], culture: dict[str, Any]) -> dict[str, Any]:
    old = read_json(COG / "beliefs.json", {})
    if not isinstance(old, dict):
        old = {}
    beliefs: dict[str, Any] = {}
    public_incidents = [e for e in cyber[-12:] if e.get("result") == "success" and e.get("impact")]
    all_culture = [x.get("signal") for x in culture.get("city_signals", [])[:4] if isinstance(x, dict)]
    for name in names:
        faction = member_to_faction.get(name)
        contacts = contact_summary(name) if name in active else []
        prior = old.get(name) if isinstance(old.get(name), dict) else {}
        awareness: list[dict[str, Any]] = []
        if faction in {"ThAI Guardians", "Obsidian Network"}:
            source = cyber[-8:]
            for e in source:
                awareness.append({
                    "claim": f"Recent simulated {str(e.get('threat') or 'cyber').replace('_',' ')} activity involved {e.get('target') or 'Detroit infrastructure'}.",
                    "confidence": 0.78 if faction == "ThAI Guardians" and e.get("detected") else 0.62,
                    "source": "faction intelligence",
                })
        else:
            for e in public_incidents[-3:]:
                awareness.append({
                    "claim": f"A service disruption was reported around {e.get('target') or 'Detroit infrastructure'}.",
                    "confidence": 0.45,
                    "source": "public consequence",
                })
        beliefs[name] = {
            "created_at": prior.get("created_at") or now(),
            "updated_at": now(),
            "active": name in active,
            "faction": faction or "Neutral",
            "known_people": contacts,
            "cyber_awareness": awareness,
            "cultural_exposure": all_culture + (["evidence over opinion", "defense in depth"] if faction == "ThAI Guardians" else (["secrecy", "information advantage"] if faction == "Obsidian Network" else [])),
            "epistemic_rule": "Beliefs can be incomplete or wrong. Hidden world truth is not available unless learned through events, contact, investigation, or institutional memory.",
        }
    write_json(COG / "beliefs.json", beliefs)
    return beliefs


def backend_models() -> tuple[str, str, str, str]:
    cfg = read_json(WORLD / "config.json", {})
    models = cfg.get("models") if isinstance(cfg, dict) and isinstance(cfg.get("models"), dict) else {}
    backend_path = ROOT / "runtime" / "llama" / "active_backend"
    try:
        backend = backend_path.read_text(encoding="utf-8").strip() or "unknown"
    except Exception:
        backend = "unknown"
    role = cfg.get("role_model") if isinstance(cfg, dict) else None
    if isinstance(role, list):
        role_default = str(role[0]) if role else ""
    else:
        role_default = str(role or "")
    citizen = "liquid-citizen" if "liquid-citizen" in models and backend == "llama" else role_default
    strategy = "liquid-strategy" if "liquid-strategy" in models and backend == "llama" else str(cfg.get("god_model") or citizen)
    cyber = "cyber-specialist" if "cyber-specialist" in models and backend == "llama" and health(8083) else strategy
    return backend, citizen, strategy, cyber


def build_routing(active: set[str], member_to_faction: dict[str, str], drift: dict[str, Any], beliefs: dict[str, Any]) -> dict[str, Any]:
    backend, citizen, strategy, cyber = backend_models()
    routes: dict[str, Any] = {}
    counts = Counter()
    drift_agents = drift.get("agents") if isinstance(drift.get("agents"), dict) else {}
    for name in sorted(active, key=str.casefold):
        reasons: list[str] = []
        model = citizen
        faction = member_to_faction.get(name)
        d = drift_agents.get(name) if isinstance(drift_agents.get(name), dict) else {}
        contacts = (beliefs.get(name) or {}).get("known_people") if isinstance(beliefs.get(name), dict) else []
        if name in {"TGOT", "Morbeious"}:
            model = strategy
            reasons.append("strategic leader")
        elif faction in {"ThAI Guardians", "Obsidian Network"}:
            # v1.4.4: faction identity no longer burns the 7B cyber model for routine life.
            # Cyber escalation is now stage/task-aware in detroit_liquid_native.py.
            model = citizen
            reasons.append("faction member; cyber model reserved for cyber-heavy activity")
        if d.get("status") == "high" and model == citizen:
            model = strategy
            reasons.append("persona drift guard")
        if len(contacts or []) >= 8 and model == citizen:
            model = strategy
            reasons.append("high social-context load")
        if not reasons:
            reasons.append("routine citizen cognition")
        routes[name] = {"model": model, "reasons": reasons, "faction": faction or "Neutral"}
        counts[model] += 1
    out = {
        "version": VERSION,
        "updated_at": now(),
        "backend": backend,
        "models": {"citizen": citizen, "strategy": strategy, "cyber": cyber},
        "counts": dict(counts),
        "agents": routes,
    }
    write_json(COG / "routing.json", out)
    orchestration = {
        "version": VERSION,
        "updated_at": now(),
        "principle": "Batch routine cognition on small models; escalate only when social, strategic, cyber, or persona-fidelity pressure warrants it.",
        "backend": backend,
        "lanes": [
            {"name": "citizen", "model": citizen, "agents": counts.get(citizen, 0), "priority": 1},
            {"name": "strategy", "model": strategy, "agents": counts.get(strategy, 0), "priority": 2},
            {"name": "cyber", "model": cyber, "agents": counts.get(cyber, 0), "priority": 3},
        ],
        "continuous_batching": backend == "llama",
    }
    write_json(COG / "orchestration.json", orchestration)
    return out


def build_summary(names: list[str], active: set[str], beliefs: dict[str, Any], drift: dict[str, Any], routing: dict[str, Any], institutions: dict[str, Any], culture: dict[str, Any]) -> dict[str, Any]:
    agent_rows: dict[str, Any] = {}
    d_agents = drift.get("agents") if isinstance(drift.get("agents"), dict) else {}
    r_agents = routing.get("agents") if isinstance(routing.get("agents"), dict) else {}
    for name in active:
        b = beliefs.get(name) if isinstance(beliefs.get(name), dict) else {}
        d = d_agents.get(name) if isinstance(d_agents.get(name), dict) else {}
        r = r_agents.get(name) if isinstance(r_agents.get(name), dict) else {}
        agent_rows[name] = {
            "drift_score": d.get("score", 0),
            "drift_status": d.get("status", "unknown"),
            "model": r.get("model"),
            "routing_reasons": r.get("reasons", []),
            "faction": b.get("faction", "Neutral"),
            "known_people": len(b.get("known_people") or []),
            "belief_claims": len(b.get("cyber_awareness") or []),
        }
    inst = institutions.get("institutions") if isinstance(institutions.get("institutions"), dict) else {}
    summary = {
        "version": VERSION,
        "updated_at": now(),
        "population": len(names),
        "active_citizens": len(active),
        "beliefs": {"citizens": len(beliefs), "principle": "world truth != citizen knowledge != citizen belief"},
        "drift": drift.get("counts", {}),
        "routing": {"backend": routing.get("backend"), "counts": routing.get("counts", {}), "models": routing.get("models", {})},
        "institutions": [{"name": name, "memory_count": len((rec or {}).get("memory") or [])} for name, rec in inst.items()],
        "culture": culture.get("city_signals", [])[:6],
        "agents": agent_rows,
    }
    write_json(COG / "summary.json", summary)
    return summary


def ensure_base() -> None:
    COG.mkdir(parents=True, exist_ok=True)
    cfg = read_json(COG / "config.json", {})
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.update({
        "version": VERSION,
        "belief_truth_separation": True,
        "persona_drift_monitor": True,
        "adaptive_model_escalation": True,
        "institutional_memory": True,
        "cultural_transmission": True,
        "tai_orchestration": True,
        "automatic_personality_rewrite": False,
    })
    write_json(COG / "config.json", cfg)


def update() -> dict[str, Any]:
    ensure_base()
    names = population_names()
    active = active_names()
    factions, member_to_faction = faction_index()
    baselines = ensure_baselines(names)
    drift = drift_report(sorted(active, key=str.casefold), baselines)
    cyber, audits = recent_cyber_events()
    truth = build_truth(names, factions)
    institutions = build_institutions(factions, cyber, audits)
    dt_state = read_json(DT / "state.json", {})
    culture = build_culture(dt_state if isinstance(dt_state, dict) else {}, factions)
    beliefs = build_beliefs(names, active, member_to_faction, cyber, audits, culture)
    routing = build_routing(active, member_to_faction, drift, beliefs)
    summary = build_summary(names, active, beliefs, drift, routing, institutions, culture)
    append_ndjson(COG / "events.ndjson", {"time": now(), "type": "cognition_tick", "checkpoint": truth.get("checkpoint"), "active": len(active), "routing": routing.get("counts", {})})
    return summary


_cache: dict[str, Any] = {"stamp": None, "beliefs": {}, "baselines": {}, "drift": {}, "routing": {}, "culture": {}, "institutions": {}}


def _refresh_cache() -> None:
    paths = [COG / "beliefs.json", COG / "persona_baselines.json", COG / "drift_report.json", COG / "routing.json", COG / "culture.json", COG / "institutions.json"]
    stamp = tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in paths)
    if stamp == _cache.get("stamp"):
        return
    _cache["stamp"] = stamp
    _cache["beliefs"] = read_json(paths[0], {})
    _cache["baselines"] = read_json(paths[1], {})
    _cache["drift"] = read_json(paths[2], {})
    _cache["routing"] = read_json(paths[3], {})
    _cache["culture"] = read_json(paths[4], {})
    _cache["institutions"] = read_json(paths[5], {})


def route_for(name: str) -> str | None:
    _refresh_cache()
    routes = _cache.get("routing", {}).get("agents", {}) if isinstance(_cache.get("routing"), dict) else {}
    rec = routes.get(name) if isinstance(routes, dict) else None
    return str(rec.get("model")) if isinstance(rec, dict) and rec.get("model") else None


def context_for(name: str) -> str:
    _refresh_cache()
    beliefs = _cache.get("beliefs") if isinstance(_cache.get("beliefs"), dict) else {}
    baselines = _cache.get("baselines") if isinstance(_cache.get("baselines"), dict) else {}
    drift = _cache.get("drift") if isinstance(_cache.get("drift"), dict) else {}
    culture = _cache.get("culture") if isinstance(_cache.get("culture"), dict) else {}
    institutions = _cache.get("institutions") if isinstance(_cache.get("institutions"), dict) else {}
    b = beliefs.get(name) if isinstance(beliefs.get(name), dict) else {}
    base = baselines.get(name) if isinstance(baselines.get(name), dict) else {}
    d = (drift.get("agents") or {}).get(name, {}) if isinstance(drift.get("agents"), dict) else {}
    known = [str(x.get("person")) for x in (b.get("known_people") or [])[:6] if isinstance(x, dict) and x.get("person")]
    awareness = [str(x.get("claim")) for x in (b.get("cyber_awareness") or [])[:3] if isinstance(x, dict) and x.get("claim")]
    cultural = [str(x) for x in (b.get("cultural_exposure") or [])[:5]]
    faction = str(b.get("faction") or "Neutral")
    inst_block = institutions.get("institutions") if isinstance(institutions.get("institutions"), dict) else {}
    mems = []
    if faction in inst_block and isinstance(inst_block[faction], dict):
        mems = [str(x.get("summary")) for x in (inst_block[faction].get("memory") or [])[-3:] if isinstance(x, dict) and x.get("summary")]
    lines = [
        "## Cognitive Society Context",
        "This is your private current knowledge and belief state. It can be incomplete or wrong. Do not assume hidden world truth you have not learned.",
        f"- Faction/institution: {faction}",
    ]
    if known:
        lines.append("- People you currently know through direct contact: " + ", ".join(known))
    if awareness:
        lines.append("- Current cyber/world beliefs: " + " | ".join(awareness))
    if mems:
        lines.append("- Institutional memory available to you: " + " | ".join(mems))
    if cultural:
        lines.append("- Cultural influences around you: " + ", ".join(cultural))
    if base:
        anchors = []
        if base.get("core_motivation"): anchors.append("motivation=" + str(base.get("core_motivation"))[:180])
        if base.get("values"): anchors.append("values=" + str(base.get("values"))[:180])
        if anchors:
            lines.append("- Long-term identity anchors: " + " | ".join(anchors))
    if d.get("status") in {"watch", "high"}:
        lines.append(f"- Persona fidelity guard: drift status={d.get('status')} score={d.get('score')}. Remain consistent with your established identity unless lived experiences justify change.")
    return "\n".join(lines)[:2200]


def apply_assignment() -> None:
    routing = read_json(COG / "routing.json", {})
    routes = routing.get("agents") if isinstance(routing, dict) and isinstance(routing.get("agents"), dict) else {}
    if not routes:
        return
    cfg = read_json(WORLD / "config.json", {})
    valid = set((cfg.get("models") or {}).keys()) if isinstance(cfg, dict) and isinstance(cfg.get("models"), dict) else set()
    assignment_path = WORLD / "model_assignment.json"
    assignment = read_json(assignment_path, {})
    if not isinstance(assignment, dict):
        assignment = {}
    changed = False
    for name, rec in routes.items():
        if not isinstance(rec, dict):
            continue
        model = str(rec.get("model") or "")
        if model and (not valid or model in valid) and assignment.get(name) != model:
            assignment[name] = model
            changed = True
    if changed:
        write_json(assignment_path, dict(sorted(assignment.items())))


def apply_runtime_patches() -> None:
    from src.agents.data_manager import DataManager
    from src.agents.role_agent import RoleAgent

    if not getattr(DataManager.character_prompt, "_agentopia_cognition_v130", False):
        original_prompt = DataManager.character_prompt
        def cognitive_prompt(self):
            base = original_prompt(self)
            try:
                ctx = context_for(self.char)
            except Exception:
                ctx = ""
            return base + ("\n\n" + ctx if ctx else "")
        cognitive_prompt._agentopia_cognition_v130 = True
        DataManager.character_prompt = cognitive_prompt

    if not getattr(RoleAgent._generate_with_functions, "_agentopia_cognition_v130", False):
        original_generate = RoleAgent._generate_with_functions
        def adaptive_generate(self, inputs, *args, **kwargs):
            if kwargs.get("model_override") is not None:
                return original_generate(self, inputs, *args, **kwargs)
            routed = None
            try:
                routed = route_for(self.name)
            except Exception:
                routed = None
            if not routed or routed == self.model:
                return original_generate(self, inputs, *args, **kwargs)
            old_model = self.model
            old_dm_model = getattr(self.dm, "model", None)
            self.model = routed
            if hasattr(self.dm, "model"):
                self.dm.model = routed
            try:
                return original_generate(self, inputs, *args, **kwargs)
            finally:
                self.model = old_model
                if hasattr(self.dm, "model"):
                    self.dm.model = old_dm_model
        adaptive_generate._agentopia_cognition_v130 = True
        RoleAgent._generate_with_functions = adaptive_generate


def status() -> None:
    s = read_json(COG / "summary.json", {})
    print(f"Agentopia Detroit Cognitive Society v{VERSION}")
    print("Belief model:", (s.get("beliefs") or {}).get("principle", "not initialized"))
    print("Population:", s.get("population", 0), "active:", s.get("active_citizens", 0))
    print("Drift:", s.get("drift", {}))
    print("Routing:", (s.get("routing") or {}).get("counts", {}))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["init", "update", "status"], nargs="?", default="update")
    args = ap.parse_args()
    if args.command == "init":
        ensure_base(); update(); status()
    elif args.command == "status":
        status()
    else:
        update(); status()
