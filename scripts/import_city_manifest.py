#!/usr/bin/env python3
"""City Builder staging importer. No live-world mutation or engine launch."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "agentopia.city.manifest.v1"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")
MAX_BYTES = 2_000_000
MAX_ITEMS = 3000
FIELDS = ("street_names", "neighborhood_names", "named_places")


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("Expected agentopia.city.manifest.v1")
    wid = data.get("world_id")
    if not isinstance(wid, str) or not ID_RE.fullmatch(wid):
        raise ValueError("Invalid world_id (2-49 lowercase letters, numbers or hyphens)")
    if wid in ("detroit", "detroit-persistent", "detroit_persistent"):
        raise ValueError("Reserved Detroit world ID; choose a new distinct world ID")
    for field in ("display_name", "country"):
        if not isinstance(data.get(field), str) or not data[field].strip() or len(data[field]) > 160:
            raise ValueError("Invalid " + field)
    loc = data.get("location")
    if not isinstance(loc, dict):
        raise ValueError("Missing location")
    for field, lo, hi in (("latitude", -90, 90), ("longitude", -180, 180)):
        value = loc.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ValueError("Invalid " + field)
    geography = data.get("geography")
    if not isinstance(geography, dict):
        raise ValueError("Missing geography")
    for key in FIELDS:
        items = geography.get(key)
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise ValueError("Invalid geography." + key)
        if any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in items):
            raise ValueError("Invalid name in geography." + key)
    deployment = data.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("mode") != "staging_only" or deployment.get("does_not_modify_active_world") is not True:
        raise ValueError("Only staging-only manifests are accepted")
    provenance = data.get("provenance", [])
    if not isinstance(provenance, list) or len(provenance) > 100:
        raise ValueError("Invalid provenance")
    for key in ("timezone", "climate_profile", "region", "notes"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 4000):
            raise ValueError("Invalid " + key)
    return data


def unique_names(values):
    out, seen = [], set()
    for name in values:
        name = name.strip()
        if name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out


def sha256_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def city_bundle(data):
    geo = data["geography"]
    streets = unique_names(geo["street_names"])
    areas = unique_names(geo["neighborhood_names"])
    places = unique_names(geo["named_places"])
    profile = {
        "schema": "agentopia.city.profile.v1",
        "world_id": data["world_id"],
        "display_name": data["display_name"].strip(),
        "region": (data.get("region") or "").strip(),
        "country": data["country"].strip(),
        "location": data["location"],
        "timezone": data.get("timezone"),
        "climate_profile": data.get("climate_profile"),
        "source_license_note": data.get("source_license_note", "Check source attribution and redistribution obligations"),
        "provenance": data.get("provenance", []),
        "notes": data.get("notes", ""),
        "fictional_extension": True,
    }
    geography = {
        "schema": "agentopia.city.geography.v1",
        "world_id": data["world_id"],
        "streets": [{"id": f"street-{i:04d}", "name": name} for i, name in enumerate(streets, 1)],
        "neighborhoods": [{"id": f"area-{i:04d}", "name": name} for i, name in enumerate(areas, 1)],
        "places": [{"id": f"place-{i:04d}", "name": name} for i, name in enumerate(places, 1)],
        "coverage": "sample_or_manually_edited_not_a_complete_city",
    }
    return profile, geography


def stage(manifest_path, output_root, dry_run=False):
    manifest_path = Path(manifest_path).expanduser().resolve()
    if manifest_path.stat().st_size > MAX_BYTES:
        raise ValueError("Manifest too large")
    data = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    profile, geography = city_bundle(data)
    output_root = Path(output_root).expanduser().resolve()
    # Only create NEW isolated world directories. No implicit source world copying.
    target = output_root / ("city_" + data["world_id"])
    if target.is_symlink() or target.exists():
        raise FileExistsError("World directory already exists; will not overwrite: " + str(target))
    digest = sha256_json(data)
    summary = {
        "ok": True,
        "world_id": data["world_id"],
        "target": str(target),
        "manifest_sha256": digest,
        "counts": {key: len(geography[dest]) for key, dest in
                   (("street_names", "streets"), ("neighborhood_names", "neighborhoods"), ("named_places", "places"))},
        "status": "STAGED_ONLY",
        "launch_ready": False,
        "blockers": [
            "Persistent runner is hardcoded to data/detroit_persistent and must be parameterized",
            "No persona population/configuration has been generated or validated",
            "City-specific lifecycle, mobility, economy, culture and weather authorities are not parameterized",
            "City streets are a named sample, not a routable road graph",
        ],
    }
    if dry_run:
        return summary
    output_root.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".city-import-", dir=output_root))
    try:
        (temp / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp / "geography.json").write_text(json.dumps(geography, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["created_at_utc"] = datetime.now(timezone.utc).isoformat()
        (temp / "import_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (temp / "DO_NOT_LAUNCH.txt").write_text(
            "Staged City Builder data only. NOT a runnable world. Do not point the Detroit engine here.\n",
            encoding="utf-8")
        temp.rename(target)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Convert City Builder manifest into a NEW isolated staging directory")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "city_imports")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        report = stage(args.manifest, args.output_root, args.dry_run)
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
