from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DOMESTIC = [('Chicago', 'Illinois'), ('Atlanta', 'Georgia'), ('Cleveland', 'Ohio'), ('Pittsburgh', 'Pennsylvania'), ('New York City', 'New York'), ('Boston', 'Massachusetts'), ('Baltimore', 'Maryland'), ('Washington', 'District of Columbia'), ('New Orleans', 'Louisiana'), ('Houston', 'Texas'), ('Dallas', 'Texas'), ('Austin', 'Texas'), ('Los Angeles', 'California'), ('San Francisco', 'California'), ('Seattle', 'Washington'), ('Portland', 'Oregon'), ('Phoenix', 'Arizona'), ('Denver', 'Colorado'), ('Minneapolis', 'Minnesota'), ('St. Louis', 'Missouri'), ('Nashville', 'Tennessee'), ('Miami', 'Florida'), ('Charlotte', 'North Carolina'), ('Philadelphia', 'Pennsylvania'), ('Milwaukee', 'Wisconsin')]
INTERNATIONAL = [('Windsor', 'Canada'), ('Toronto', 'Canada'), ('Montreal', 'Canada'), ('Mexico City', 'Mexico'), ('Bogota', 'Colombia'), ('Sao Paulo', 'Brazil'), ('Lagos', 'Nigeria'), ('Accra', 'Ghana'), ('Nairobi', 'Kenya'), ('Cairo', 'Egypt'), ('Beirut', 'Lebanon'), ('Amman', 'Jordan'), ('London', 'United Kingdom'), ('Paris', 'France'), ('Berlin', 'Germany'), ('Warsaw', 'Poland'), ('Rome', 'Italy'), ('Madrid', 'Spain'), ('Mumbai', 'India'), ('Bengaluru', 'India'), ('Seoul', 'South Korea'), ('Tokyo', 'Japan'), ('Osaka', 'Japan'), ('Shanghai', 'China'), ('Singapore', 'Singapore'), ('Sydney', 'Australia')]


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def enrich_new_citizen_profile(engine: Any, profile: dict[str, Any], name: str, rng: Any, serial: int) -> dict[str, Any]:
    root = Path("data") / engine.world.data_dir
    founders_path = root / "founders.json"
    if not founders_path.exists() or not str(engine.world.data_dir).startswith("detroit_"):
        return profile
    try:
        founders_data = json.loads(founders_path.read_text(encoding="utf-8"))
        founders = list(founders_data.get("founders") or [])
    except Exception:
        founders = []
    roll = rng.random()
    if roll < 0.50 and founders:
        # Explicit blood lineage. Some citizens descend from one founder, some from two.
        n = 2 if len(founders) > 1 and rng.random() < 0.35 else 1
        picked = rng.sample(founders, n)
        lineage = {
            "type": "founder_descendant",
            "founder_ids": [x.get("founder_id") for x in picked],
            "founder_names": [x.get("name") for x in picked],
            "generation": rng.randint(1, 4),
        }
        origin = {"category":"founder_descendant", "city":"Detroit", "region":"Michigan", "country":"United States"}
        note = f"{name} is a blood-line descendant of Agentopia Detroit Founding Citizen lineage: " + ", ".join(lineage["founder_names"]) + "."
    elif roll < 0.80:
        city, region = rng.choice(DOMESTIC)
        lineage = {"type":"domestic_arrival", "founder_ids":[], "founder_names":[], "generation":None}
        origin = {"category":"domestic_arrival", "city":city, "region":region, "country":"United States"}
        note = f"{name} moved to Agentopia Detroit from {city}, {region}."
    else:
        city, country = rng.choice(INTERNATIONAL)
        lineage = {"type":"international_arrival", "founder_ids":[], "founder_names":[], "generation":None}
        origin = {"category":"international_arrival", "city":city, "region":"", "country":country}
        note = f"{name} moved to Agentopia Detroit from {city}, {country}."
    profile["lineage"] = lineage
    profile["origin"] = origin
    profile["world_role"] = "background_citizen"
    profile["brief_introduction"] = str(profile.get("brief_introduction") or "").rstrip() + " " + note
    profile["details"] = "AGENTOPIA DETROIT ORIGIN: " + note + " " + str(profile.get("details") or "")
    _append(root / "detroit_lineage.jsonl", {"name": name, "lineage": lineage, "origin": origin, "serial": serial})
    return profile
