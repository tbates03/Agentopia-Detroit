#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
HUM = WORLD / "humanity"
VERSION = "1.6.0"

# Pew global 2020 landscape, used only as a neutral fallback prior for fictional
# citizens when family belief and origin-specific context are unavailable.
# No religion is assigned from a person's name, race, ethnicity, or appearance.
GLOBAL_BELIEF_PRIOR = [
    ("Christianity", 28.8),
    ("Islam", 25.6),
    ("Unaffiliated", 24.2),
    ("Hinduism", 14.9),
    ("Buddhism", 4.1),
    ("Other / traditional / folk", 2.2),
    ("Judaism", 0.2),
]

ORIGINS = [
    "Detroit, Michigan", "Chicago, Illinois", "Atlanta, Georgia", "Cleveland, Ohio",
    "New Orleans, Louisiana", "Houston, Texas", "Los Angeles, California", "New York, New York",
    "Windsor, Ontario", "Toronto, Ontario", "Bogota, Colombia", "Sao Paulo, Brazil",
    "Lagos, Nigeria", "Accra, Ghana", "Beirut, Lebanon", "Seoul, South Korea",
    "Tokyo, Japan", "Mumbai, India", "Mexico City, Mexico", "London, United Kingdom",
]

FIRST_NAMES = [
    "Amara","Andre","Amina","Avery","Camila","Daniel","Elena","Eli","Fatima","Gabriel",
    "Hana","Isaiah","Jamal","Jiwoo","Jordan","Leila","Luis","Maya","Mei","Micah",
    "Nia","Noah","Priya","Rafael","Samira","Sofia","Tariq","Theo","Yara","Zain",
]
SURNAMES = [
    "Bennett","Campbell","Carter","Delgado","Grant","Haddad","Johnson","Khan","Kim","Li",
    "Martinez","Mensah","Okafor","Patel","Robinson","Sato","Singh","Taylor","Williams","Young",
]

LIFE_STAGES = [
    (0, 2, "baby"), (3, 5, "early_childhood"), (6, 12, "child"), (13, 17, "teen"),
    (18, 29, "young_adult"), (30, 49, "adult"), (50, 64, "middle_age"),
    (65, 79, "senior"), (80, 200, "elder"),
]


def utc_now() -> str:
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


def growth_config() -> dict[str, Any]:
    cfg = read_json(WORLD / "config.json", {})
    world = cfg.get("world") if isinstance(cfg, dict) else {}
    growth = world.get("growth") if isinstance(world, dict) else {}
    return growth if isinstance(growth, dict) else {}


def append_event(name: str, obj: dict[str, Any]) -> None:
    # .ndjson deliberately avoids Agentopia's TimeState .jsonl cleanup scanner.
    p = HUM / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def stable_rng(*parts: Any) -> random.Random:
    raw = "|".join(str(x) for x in parts)
    seed = int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def world_year() -> int:
    cp = read_json(WORLD / "checkpoint.json", {})
    try:
        return int(cp.get("year"))
    except Exception:
        cfg = read_json(WORLD / "config.json", {})
        return int(((cfg.get("world") or {}).get("time") or {}).get("start_year", 2045))


def stage_for_age(age: int) -> str:
    for lo, hi, stage in LIFE_STAGES:
        if lo <= age <= hi:
            return stage
    return "elder"


def profile_files(person_dir: Path) -> list[Path]:
    base = person_dir / "profile"
    if not base.exists(): return []
    def key(p: Path):
        m = re.search(r"year=(\d+)", p.name)
        return (int(m.group(1)) if m else -1, p.name)
    return sorted(base.glob("year=*.json"), key=key)


def birth_year_from_profile(profile: dict[str, Any], current_year: int) -> int:
    try:
        if profile.get("birth_year") is not None:
            return int(profile["birth_year"])
    except Exception:
        pass
    # Older Agentopia profiles may only encode age in prose. Do not infer from name.
    text = str(profile.get("brief_introduction") or "") + " " + str(profile.get("details") or "")
    m = re.search(r"\b(\d{1,2})-year-old\b", text, re.I)
    if m:
        age = max(0, min(100, int(m.group(1))))
        return current_year - age
    return current_year - 30


def explicit_belief(profile: dict[str, Any]) -> str | None:
    # Only explicit profile text can seed an existing persona's belief.
    text = " ".join(str(profile.get(k) or "") for k in ("details","values","preferences","brief_introduction")).lower()
    markers = [
        ("Christianity", [" christian", " church", " catholic", " baptist", " protestant", " orthodox"]),
        ("Islam", [" muslim", " islam", " mosque", " ramadan"]),
        ("Hinduism", [" hindu", " hinduism"]),
        ("Buddhism", [" buddhist", " buddhism"]),
        ("Judaism", [" jewish", " judaism", " synagogue"]),
        ("Sikhism", [" sikh", " gurdwara"]),
        ("Unaffiliated", [" atheist", " agnostic", " nonreligious", " non-religious"]),
    ]
    for belief, words in markers:
        if any(w in " " + text for w in words):
            return belief
    return None


def weighted_belief(rng: random.Random) -> str:
    x = rng.random() * sum(w for _, w in GLOBAL_BELIEF_PRIOR)
    cur = 0.0
    for name, weight in GLOBAL_BELIEF_PRIOR:
        cur += weight
        if x <= cur:
            return name
    return "Unaffiliated"


def make_belief(person_id: str, *, inherited: str | None = None, explicit: str | None = None) -> dict[str, Any]:
    rng = stable_rng("belief", person_id)
    affiliation = explicit or (inherited if inherited and rng.random() < 0.82 else weighted_belief(rng))
    if affiliation == "Unaffiliated":
        tradition = rng.choice(["agnostic", "atheist", "nothing in particular", "spiritual but unaffiliated"])
        practice = rng.choice(["none", "rare", "personal"]) 
    else:
        tradition = "unspecified tradition"
        practice = rng.choice(["rare", "monthly", "weekly", "personal"])
    return {
        "affiliation": affiliation,
        "tradition": tradition,
        "importance": rng.randint(15, 95),
        "practice": practice,
        "spirituality": rng.randint(10, 95),
        "tolerance_other_beliefs": rng.randint(65, 100),
        "belief_confidence": rng.randint(35, 95),
        "openness_to_change": rng.randint(10, 85),
        "source": "explicit_profile" if explicit else ("family_inheritance" if inherited else "global_neutral_prior"),
    }


def make_radicalization(person_id: str) -> dict[str, Any]:
    rng = stable_rng("radicalization", person_id)
    # Religion is intentionally absent from the input. Most citizens begin low risk.
    vals = {
        "grievance": rng.randint(0, 35),
        "social_isolation": rng.randint(0, 35),
        "propaganda_exposure": rng.randint(0, 25),
        "conspiracy_adoption": rng.randint(0, 20),
        "authoritarian_tendency": rng.randint(0, 40),
        "in_group_fixation": rng.randint(0, 35),
        "out_group_hostility": rng.randint(0, 15),
        "violence_acceptance": rng.randint(0, 8),
    }
    vals["risk_score"] = round(sum(vals.values()) / (8 * 100), 3)
    vals["religion_independent"] = True
    vals["status"] = "baseline"
    return vals


def person_id_for(name: str) -> str:
    return "P-" + hashlib.sha256(name.encode()).hexdigest()[:12].upper()


def load_state() -> dict[str, Any]:
    s = read_json(HUM / "people.json", {})
    return s if isinstance(s, dict) else {}


def save_state(people: dict[str, Any]) -> None:
    write_json(HUM / "people.json", people)


def seed_existing_personas(people: dict[str, Any], current_year: int) -> None:
    root = WORLD / "persona"
    if not root.exists(): return
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        pid = person_id_for(d.name)
        files = profile_files(d)
        profile = read_json(files[-1], {}) if files else {}
        by = birth_year_from_profile(profile if isinstance(profile, dict) else {}, current_year)
        age = max(0, current_year - by)
        rec = people.get(pid, {}) if isinstance(people.get(pid), dict) else {}
        rec.update({
            "person_id": pid,
            "name": d.name,
            "birth_year": by,
            "age": age,
            "life_stage": stage_for_age(age),
            "alive": rec.get("alive", True),
            "agentopia_persona": True,
            "background": (d / "_background.json").exists(),
            "origin_type": rec.get("origin_type", "founding_or_existing_citizen"),
            "origin": rec.get("origin", "Agentopia Detroit"),
            "parents": rec.get("parents", []),
            "children": rec.get("children", []),
            "partners": rec.get("partners", []),
            "household_id": rec.get("household_id"),
            "founder_id": profile.get("founder_id", rec.get("founder_id")),
            "lineage": profile.get("lineage", rec.get("lineage", {})),
            "origin_record": profile.get("origin", rec.get("origin_record", {})),
            "updated_at": utc_now(),
        })
        if "belief" not in rec:
            rec["belief"] = make_belief(pid, explicit=explicit_belief(profile if isinstance(profile, dict) else {}))
        if "radicalization" not in rec:
            rec["radicalization"] = make_radicalization(pid)
        people[pid] = rec


def unique_name(rng: random.Random, people: dict[str, Any], surname: str | None = None) -> str:
    used = {str(x.get("name")) for x in people.values() if isinstance(x, dict)}
    for _ in range(100):
        name = f"{rng.choice(FIRST_NAMES)} {surname or rng.choice(SURNAMES)}"
        if name not in used: return name
    return f"Citizen {len(used)+1}"


def founder_ids_for(person: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    fid = person.get("founder_id")
    if fid:
        ids.append(str(fid))
    lineage = person.get("lineage")
    if isinstance(lineage, dict):
        ids.extend(str(x) for x in lineage.get("founder_ids", []) if x)
    return sorted(set(ids))


def inherited_lineage(*parents: dict[str, Any]) -> dict[str, Any]:
    founder_ids: list[str] = []
    for parent in parents:
        if isinstance(parent, dict):
            founder_ids.extend(founder_ids_for(parent))
    founder_ids = sorted(set(founder_ids))
    if founder_ids:
        return {
            "type": "founder_descendant",
            "founder_ids": founder_ids,
            "generation": "descendant",
        }
    return {"type": "resident_lineage", "founder_ids": [], "generation": "descendant"}


def create_person(people: dict[str, Any], name: str, age: int, current_year: int, *, origin: str, household: str, parents=None, partner=None, inherited_belief=None) -> str:
    pid = person_id_for(name + f"|{current_year}|{household}")
    rec = {
        "person_id": pid, "name": name, "birth_year": current_year-age, "age": age,
        "life_stage": stage_for_age(age), "alive": True, "agentopia_persona": False,
        "background": True, "origin_type": "migration", "origin": origin,
        "parents": list(parents or []), "children": [], "partners": [partner] if partner else [],
        "household_id": household, "belief": make_belief(pid, inherited=inherited_belief),
        "radicalization": make_radicalization(pid), "created_at": utc_now(), "updated_at": utc_now(),
    }
    people[pid] = rec
    return pid


def seed_migration_households(people: dict[str, Any], current_year: int) -> None:
    marker = HUM / "migration_seed_v140.json"
    if marker.exists(): return
    rng = stable_rng("migration_seed_v140", current_year)
    created = []

    # Extended family: grandparents -> adult siblings -> grandchildren. This creates
    # grandparents, aunts/uncles, nieces/nephews, and cousins immediately without
    # inventing family ties among the 100 founders.
    origin = rng.choice([x for x in ORIGINS if x != "Detroit, Michigan"])
    surname = rng.choice(SURNAMES)
    h1 = "HH-" + hashlib.sha256((origin+surname+"A").encode()).hexdigest()[:8].upper()
    gp1 = create_person(people, unique_name(rng, people, surname), 72, current_year, origin=origin, household=h1)
    gp2 = create_person(people, unique_name(rng, people, surname), 69, current_year, origin=origin, household=h1, partner=gp1)
    people[gp1]["partners"]=[gp2]
    belief = people[gp1]["belief"]["affiliation"]
    a1 = create_person(people, unique_name(rng, people, surname), 39, current_year, origin=origin, household=h1, parents=[gp1,gp2], inherited_belief=belief)
    a2 = create_person(people, unique_name(rng, people, surname), 36, current_year, origin=origin, household=h1, parents=[gp1,gp2], inherited_belief=belief)
    people[gp1]["children"]=[a1,a2]; people[gp2]["children"]=[a1,a2]
    p1 = create_person(people, unique_name(rng, people), 38, current_year, origin=origin, household=h1, partner=a1)
    people[a1]["partners"]=[p1]
    c1 = create_person(people, unique_name(rng, people, surname), 14, current_year, origin=origin, household=h1, parents=[a1,p1], inherited_belief=belief)
    c2 = create_person(people, unique_name(rng, people, surname), 1, current_year, origin=origin, household=h1, parents=[a1,p1], inherited_belief=belief)
    people[a1]["children"]=[c1,c2]; people[p1]["children"]=[c1,c2]
    p2 = create_person(people, unique_name(rng, people), 35, current_year, origin=origin, household=h1, partner=a2)
    people[a2]["partners"]=[p2]
    c3 = create_person(people, unique_name(rng, people, surname), 9, current_year, origin=origin, household=h1, parents=[a2,p2], inherited_belief=belief)
    c4 = create_person(people, unique_name(rng, people, surname), 4, current_year, origin=origin, household=h1, parents=[a2,p2], inherited_belief=belief)
    people[a2]["children"]=[c3,c4]; people[p2]["children"]=[c3,c4]
    created += [gp1,gp2,a1,a2,p1,p2,c1,c2,c3,c4]

    # Second migration household provides another baby/teen/senior mix.
    origin2 = rng.choice([x for x in ORIGINS if x not in (origin,"Detroit, Michigan")])
    surname2 = rng.choice([s for s in SURNAMES if s != surname])
    h2 = "HH-" + hashlib.sha256((origin2+surname2+"B").encode()).hexdigest()[:8].upper()
    senior = create_person(people, unique_name(rng, people, surname2), 81, current_year, origin=origin2, household=h2)
    adult = create_person(people, unique_name(rng, people, surname2), 48, current_year, origin=origin2, household=h2, parents=[senior], inherited_belief=people[senior]["belief"]["affiliation"])
    teen = create_person(people, unique_name(rng, people, surname2), 17, current_year, origin=origin2, household=h2, parents=[adult], inherited_belief=people[adult]["belief"]["affiliation"])
    baby = create_person(people, unique_name(rng, people, surname2), 0, current_year, origin=origin2, household=h2, parents=[adult], inherited_belief=people[adult]["belief"]["affiliation"])
    people[senior]["children"]=[adult]; people[adult]["children"]=[teen,baby]
    created += [senior,adult,teen,baby]

    write_json(marker, {"version": VERSION, "created_at": utc_now(), "world_year": current_year, "people_created": created, "note": "Fictional migration households; no founder family ties invented."})
    append_event("lifecycle_events.ndjson", {"event":"migration_households_arrived","time":utc_now(),"world_year":current_year,"people":created})


def kinship(people: dict[str, Any]) -> dict[str, Any]:
    children_of = defaultdict(set)
    parents_of = defaultdict(set)
    partners = defaultdict(set)
    for pid, p in people.items():
        if not isinstance(p, dict): continue
        for par in p.get("parents", []):
            parents_of[pid].add(par); children_of[par].add(pid)
        for ch in p.get("children", []):
            children_of[pid].add(ch); parents_of[ch].add(pid)
        for q in p.get("partners", []): partners[pid].add(q)
    result = {}
    for pid in people:
        siblings=set()
        for par in parents_of[pid]: siblings |= children_of[par]
        siblings.discard(pid)
        grandparents=set()
        for par in parents_of[pid]: grandparents |= parents_of[par]
        grandchildren=set()
        for ch in children_of[pid]: grandchildren |= children_of[ch]
        aunts_uncles=set()
        for par in parents_of[pid]:
            for g in parents_of[par]: aunts_uncles |= children_of[g]
            aunts_uncles.discard(par)
        nieces_nephews=set()
        for sib in siblings: nieces_nephews |= children_of[sib]
        cousins=set()
        for au in aunts_uncles: cousins |= children_of[au]
        result[pid] = {
            "parents": sorted(parents_of[pid]), "children": sorted(children_of[pid]),
            "siblings": sorted(siblings), "grandparents": sorted(grandparents),
            "grandchildren": sorted(grandchildren), "aunts_uncles": sorted(aunts_uncles),
            "nieces_nephews": sorted(nieces_nephews), "cousins": sorted(cousins),
            "partners": sorted(partners[pid]),
        }
    return result


def update_ages(people: dict[str, Any], current_year: int) -> None:
    for p in people.values():
        if not isinstance(p, dict) or not p.get("alive", True): continue
        try: age=max(0,current_year-int(p.get("birth_year", current_year)))
        except Exception: age=0
        p["age"]=age; p["life_stage"]=stage_for_age(age); p["updated_at"]=utc_now()


def process_year_transition(people: dict[str, Any], current_year: int) -> None:
    state = read_json(HUM / "lifecycle_state.json", {})
    last = int(state.get("last_processed_year", current_year))
    if not state:
        write_json(HUM / "lifecycle_state.json", {"last_processed_year": current_year, "initialized_at": utc_now()})
        return
    if current_year <= last: return
    for year in range(last+1, current_year+1):
        # Belief change is uncommon and person-driven; family affiliation itself is not a risk factor.
        for pid,p in list(people.items()):
            if not isinstance(p,dict) or not p.get("alive",True): continue
            b=p.get("belief") or {}
            rng=stable_rng("belief_switch",pid,year)
            openness=int(b.get("openness_to_change",0))
            if rng.random() < max(0.001, openness/10000):
                old=str(b.get("affiliation") or "Unaffiliated")
                new=weighted_belief(rng)
                if new!=old:
                    b["affiliation"]=new; b["source"]="life_experience_switch"; b["belief_confidence"]=rng.randint(35,85)
                    append_event("belief_events.ndjson",{"event":"belief_change","time":utc_now(),"world_year":year,"person_id":pid,"from":old,"to":new})
        # Mortality is a coarse fictional simulation mechanic, not a medical forecast.
        for pid,p in list(people.items()):
            if not isinstance(p,dict) or not p.get("alive",True): continue
            age=year-int(p.get("birth_year",year))
            rate=0.0005 if age<50 else 0.002 if age<65 else 0.01 if age<80 else 0.05 if age<90 else 0.12
            if stable_rng("mortality",pid,year).random() < rate:
                p["alive"]=False; p["death_year"]=year; p["life_stage"]="deceased"
                append_event("lifecycle_events.ndjson",{"event":"death","time":utc_now(),"world_year":year,"person_id":pid,"age":age})
        # Partnerships already represented in family graph can have children. This avoids inferring romance from mere contact.
        seen=set()
        for pid,p in list(people.items()):
            if not isinstance(p,dict) or not p.get("alive",True): continue
            for partner in p.get("partners",[]):
                pair=tuple(sorted((pid,partner)))
                if pair in seen or partner not in people: continue
                seen.add(pair)
                q=people[partner]
                if not q.get("alive",True): continue
                ages=(year-int(p.get("birth_year",year)),year-int(q.get("birth_year",year)))
                if min(ages)<18 or max(ages)>55: continue
                existing=len(set(p.get("children",[])) & set(q.get("children",[])))
                chance=max(0.0,0.09-(existing*0.025))
                rng=stable_rng("birth",pair,year)
                if rng.random()<chance:
                    surname=str(p.get("name","Citizen")).split()[-1]
                    name=unique_name(rng,people,surname)
                    inherited=(p.get("belief") or {}).get("affiliation")
                    child=create_person(people,name,0,year,origin="Agentopia Detroit",household=str(p.get("household_id") or q.get("household_id") or "HH-DETROIT"),parents=[pid,partner],inherited_belief=inherited)
                    people[child]["origin_type"]="founder_or_resident_lineage"
                    people[child]["lineage"]=inherited_lineage(p,q)
                    p.setdefault("children",[]).append(child); q.setdefault("children",[]).append(child)
                    append_event("lifecycle_events.ndjson",{"event":"birth","time":utc_now(),"world_year":year,"person_id":child,"parents":[pid,partner],"lineage":people[child]["lineage"]})

        # Persistent cities need arrivals as well as births. This is deliberately
        # small, deterministic and bounded so population can grow without exploding
        # local inference cost. Origin never determines religion, race, ethnicity,
        # gender, personality or skill.
        growth=growth_config()
        alive_count=sum(1 for x in people.values() if isinstance(x,dict) and x.get("alive",True))
        rate=float(growth.get("annual_migration_rate",0.02))
        minimum=max(0,int(growth.get("annual_migration_min",2)))
        maximum=max(minimum,int(growth.get("annual_migration_max",8)))
        arrivals=max(minimum,min(maximum,int(round(alive_count*rate))))
        rng=stable_rng("annual_migration",year)
        arrived=[]
        age_pool=[18,19,21,23,25,27,30,33,36,40,45,50,56,63,70]
        for idx in range(arrivals):
            origin=rng.choice([x for x in ORIGINS if x!="Detroit, Michigan"])
            age=rng.choice(age_pool)
            surname=rng.choice(SURNAMES)
            name=unique_name(rng,people,surname)
            household="HH-MIG-"+hashlib.sha256(f"{year}|{idx}|{name}".encode()).hexdigest()[:10].upper()
            newcomer=create_person(people,name,age,year,origin=origin,household=household)
            people[newcomer]["origin_type"]="annual_migration"
            arrived.append(newcomer)
        if arrived:
            append_event("lifecycle_events.ndjson",{"event":"annual_migration","time":utc_now(),"world_year":year,"people":arrived,"count":len(arrived)})
        write_json(HUM / "lifecycle_state.json", {"last_processed_year": year, "updated_at": utc_now(), "annual_arrivals": len(arrived)})


def update_radicalization(people: dict[str, Any], current_year: int) -> list[dict[str, Any]]:
    interventions=[]
    for pid,p in people.items():
        if not isinstance(p,dict) or not p.get("alive",True): continue
        r=p.setdefault("radicalization",make_radicalization(pid))
        rng=stable_rng("rad_update",pid,current_year)
        # Small social drift independent of faith. Deepfake/propaganda exposure can vary over time.
        for key,delta in (("grievance",2),("social_isolation",2),("propaganda_exposure",4),("conspiracy_adoption",2),("in_group_fixation",2),("out_group_hostility",1),("violence_acceptance",1)):
            r[key]=max(0,min(100,int(r.get(key,0))+rng.randint(-delta,delta)))
        risk=(int(r.get("grievance",0))+int(r.get("social_isolation",0))+int(r.get("propaganda_exposure",0))+int(r.get("conspiracy_adoption",0))+int(r.get("authoritarian_tendency",0))+int(r.get("in_group_fixation",0))+int(r.get("out_group_hostility",0))+2*int(r.get("violence_acceptance",0)))/(9*100)
        r["risk_score"]=round(risk,3); r["religion_independent"]=True
        if risk>=0.55 or int(r.get("violence_acceptance",0))>=55:
            r["status"]="intervention_recommended"
            interventions.append({"person_id":pid,"name":p.get("name"),"risk_score":round(risk,3),"response":"community/family support + Guardian threat-assessment review; no automatic criminal label"})
        elif risk>=0.35: r["status"]="watch_support"
        else: r["status"]="baseline"
    write_json(HUM / "intervention_queue.json", {"updated_at":utc_now(),"religion_independent":True,"cases":interventions})
    return interventions


def _stable_singleton_household(person_id: str) -> str:
    digest = hashlib.sha256(f"singleton-household|{person_id}".encode("utf-8")).hexdigest()[:10].upper()
    return f"HH-P-{digest}"


def reconcile_household_ids(people: dict[str, Any]) -> dict[str, int]:
    """Make lifecycle household IDs persistent and compatible with Human Economy.

    Explicit family household IDs always win. For older personas that entered
    Agentopia before lifecycle households existed, preserve any existing Human
    Economy household ID so housing/budget history is not discarded. Only
    citizens with neither source receive a deterministic singleton household.
    """
    econ_doc = read_json(WORLD / "human_economy" / "households.json", {})
    econ_households = econ_doc.get("households", {}) if isinstance(econ_doc, dict) else {}
    econ_by_name: dict[str, str] = {}
    if isinstance(econ_households, dict):
        # Prefer households with budget history, then newest update, then ID.
        ranked: list[tuple[int, str, str, str]] = []
        for hid, rec in econ_households.items():
            if not isinstance(rec, dict):
                continue
            rank = 1 if rec.get("last_budget") else 0
            updated = str(rec.get("updated_at") or "")
            for name in rec.get("members", []) or []:
                if name:
                    ranked.append((rank, updated, str(hid), str(name)))
        ranked.sort(reverse=True)
        for _, _, hid, name in ranked:
            econ_by_name.setdefault(name, hid)

    preserved = 0
    inherited = 0
    created = 0
    for pid, person in people.items():
        if not isinstance(person, dict) or not person.get("alive", True):
            continue
        current = str(person.get("household_id") or "").strip()
        if current and current != "unassigned":
            preserved += 1
            continue
        name = str(person.get("name") or "")
        existing = econ_by_name.get(name)
        if existing:
            person["household_id"] = existing
            person["household_source"] = "human_economy_existing"
            inherited += 1
        else:
            person["household_id"] = _stable_singleton_household(str(pid))
            person["household_source"] = "lifecycle_stable_singleton"
            created += 1
        person["updated_at"] = utc_now()
    return {"preserved": preserved, "inherited_from_economy": inherited, "created_singletons": created}


def build_households(people: dict[str, Any]) -> dict[str, Any]:
    hh=defaultdict(list)
    for pid,p in people.items():
        if not isinstance(p,dict) or not p.get("alive",True):
            continue
        hid = str(p.get("household_id") or _stable_singleton_household(str(pid)))
        hh[hid].append(pid)
    return {k:{"household_id":k,"members":sorted(v),"size":len(v)} for k,v in sorted(hh.items())}


def context_for(name: str) -> str:
    people=load_state(); pid=None
    for k,p in people.items():
        if isinstance(p,dict) and p.get("name")==name: pid=k; break
    if not pid: return ""
    p=people[pid]; kin=read_json(HUM/"kinship.json",{}).get(pid,{})
    names={k:v.get("name",k) for k,v in people.items() if isinstance(v,dict)}
    def nn(ids): return [names.get(x,x) for x in ids][:8]
    b=p.get("belief") or {}; r=p.get("radicalization") or {}
    return "\n".join([
        "## Human Lifecycle & Family Context",
        f"- Life stage: {p.get('life_stage')} (age {p.get('age')})",
        f"- Parents: {', '.join(nn(kin.get('parents',[]))) or 'none recorded'}",
        f"- Children: {', '.join(nn(kin.get('children',[]))) or 'none recorded'}",
        f"- Siblings: {', '.join(nn(kin.get('siblings',[]))) or 'none recorded'}",
        f"- Grandparents: {', '.join(nn(kin.get('grandparents',[]))) or 'none recorded'}",
        f"- Cousins: {', '.join(nn(kin.get('cousins',[]))) or 'none recorded'}",
        f"- Nieces/nephews: {', '.join(nn(kin.get('nieces_nephews',[]))) or 'none recorded'}",
        "## Belief & Worldview Context",
        f"- Affiliation: {b.get('affiliation','unspecified')} (importance {b.get('importance','?')}/100; practice {b.get('practice','unspecified')})",
        f"- Tolerance of other beliefs: {b.get('tolerance_other_beliefs','?')}/100",
        "- Belief may evolve through life experience. Do not stereotype anyone based on religion or nonreligion.",
        "## Safety / Radicalization Context",
        f"- Radicalization status: {r.get('status','baseline')} (modeled independently from religion)",
        "- Extremism is behavioral/ideological, not a property of any faith. Treat uncertainty and evidence separately.",
    ])


def write_summary(people: dict[str, Any], current_year: int, interventions: list[dict[str,Any]], household_reconciliation: dict[str,int] | None = None) -> dict[str, Any]:
    kin=kinship(people); write_json(HUM/"kinship.json",kin)
    households=build_households(people); write_json(HUM/"households.json",households)
    counts=Counter()
    beliefs=Counter()
    relations=Counter()
    for pid,p in people.items():
        if not isinstance(p,dict) or not p.get("alive",True): continue
        counts[str(p.get("life_stage") or "unknown")]+=1
        beliefs[str((p.get("belief") or {}).get("affiliation") or "unspecified")]+=1
        k=kin.get(pid,{})
        for rel in ("parents","children","siblings","grandparents","grandchildren","aunts_uncles","nieces_nephews","cousins","partners"):
            if k.get(rel): relations[rel]+=1
    activation=[]
    for pid,p in people.items():
        if not isinstance(p,dict) or not p.get("alive",True) or p.get("agentopia_persona"): continue
        if p.get("life_stage") in ("teen","young_adult","adult"):
            activation.append({"person_id":pid,"name":p.get("name"),"age":p.get("age"),"stage":p.get("life_stage"),"reason":"eligible for active-agent promotion when socially relevant"})
    write_json(HUM/"activation_queue.json",{"updated_at":utc_now(),"candidate_count":len(activation),"candidates":activation})
    summary={
        "version":VERSION,"updated_at":utc_now(),"world_year":current_year,
        "population":sum(counts.values()),"life_stages":dict(counts),"beliefs":dict(beliefs),
        "households":len(households),"kinship_presence":dict(relations),
        "household_truth":"humanity.people.household_id",
        "household_reconciliation":household_reconciliation or {},
        "interventions":len(interventions),"activation_candidates":len(activation),
        "principles":{
            "children_use_background_simulation":True,"religion_never_inferred_from_name_or_ethnicity":True,
            "radicalization_independent_of_religion":True,"belief_switching_supported":True,
            "family_graph_persistent":True,"inheritance_ledger_supported":True,
            "annual_migration_supported":True,"background_to_persona_promotion_supported":True,
        },
    }
    write_json(HUM/"summary.json",summary)
    return summary


def update() -> dict[str, Any]:
    HUM.mkdir(parents=True,exist_ok=True)
    year=world_year(); people=load_state()
    seed_existing_personas(people,year)
    seed_migration_households(people,year)
    update_ages(people,year)
    process_year_transition(people,year)
    update_ages(people,year)
    interventions=update_radicalization(people,year)
    household_reconciliation=reconcile_household_ids(people)
    save_state(people)
    return write_summary(people,year,interventions,household_reconciliation)


def apply_runtime_patch() -> None:
    from src.agents.data_manager import DataManager
    if getattr(DataManager.character_prompt,"_agentopia_humanity_v140",False): return
    original=DataManager.character_prompt
    def human_prompt(self):
        base=original(self)
        try: ctx=context_for(self.char)
        except Exception: ctx=""
        return base+("\n\n"+ctx if ctx else "")
    human_prompt._agentopia_humanity_v140=True
    DataManager.character_prompt=human_prompt


def status() -> None:
    s=read_json(HUM/"summary.json",{})
    print(f"Agentopia Detroit Human Lifecycle v{VERSION}")
    print("Population:",s.get("population",0),"households:",s.get("households",0))
    print("Life stages:",s.get("life_stages",{}))
    print("Beliefs:",s.get("beliefs",{}))
    print("Interventions:",s.get("interventions",0))

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["init","update","status"],nargs="?",default="update")
    args=ap.parse_args()
    if args.command in ("init","update"): update()
    status()
