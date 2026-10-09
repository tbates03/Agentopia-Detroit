#!/usr/bin/env python3

from pathlib import Path
import json
import re
import sys

ROOT = Path.home() / "AI" / "Agentopia"
WORLD = ROOT / "data" / "detroit_persistent"

# These are CURRENT-STATE violations when used as a person's
# current residence, job, school, commute, business or location.
LEGACY_CURRENT = [
    r"\bNYU\b",
    r"\bNew York University\b",
    r"\bManhattan\b",
    r"\bBrooklyn\b",
    r"\bBronx\b",
    r"\bQueens\b",
    r"\bStaten Island\b",
    r"\bLong Island City\b",
    r"\bGreenwich Village\b",
    r"\bNYC\b",
    r"\bNYPD\b",
    r"\bFDNY\b",
    r"\bBremer Apartment\b",
]

# Historical/origin data is intentionally NOT rewritten.
HISTORICAL_PATH_MARKERS = [
    "/generation/",
    "/contact/",
    "/memory/",
    "/god/",
    "/events.",
    "/ledger.",
    "detroit_lineage.jsonl",
    "year=2020.json",
]

CURRENT_FILES = [
    WORLD / "locations.json",
    WORLD / "career" / "state.json",
    WORLD / "cognition" / "persona_baselines.json",
    WORLD / "humanity" / "people.json",
]

persona_root = WORLD / "persona"

if persona_root.exists():
    CURRENT_FILES.extend(
        persona_root.glob("*/profile/year=2045.json")
    )

rx = re.compile("|".join(LEGACY_CURRENT), re.I)

violations = []

def walk(value, path=""):
    if isinstance(value, dict):
        for key, val in value.items():
            walk(val, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, val in enumerate(value):
            walk(val, f"{path}[{i}]")
    elif isinstance(value, str):
        hits = sorted(set(m.group(0) for m in rx.finditer(value)))
        if hits:
            violations.append((path, hits, value[:300]))

print("=" * 68)
print(" AGENTOPIA DETROIT — CURRENT-STATE GEOGRAPHY GOVERNOR")
print("=" * 68)

files_with_violations = 0

for file in sorted(CURRENT_FILES):
    if not file.exists():
        continue

    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN unreadable: {file}: {exc}")
        continue

    violations = []
    walk(data)

    if violations:
        files_with_violations += 1
        print()
        print(f"FILE: {file}")
        print(f"CURRENT-STATE VIOLATIONS: {len(violations)}")

        for path, hits, sample in violations[:20]:
            print(f"  {path}")
            print(f"    legacy={hits}")
            print(f"    {sample!r}")

        if len(violations) > 20:
            print(f"  ... {len(violations)-20} more")

print()
print("=" * 68)
print(f"FILES WITH CURRENT-STATE CONTAMINATION: {files_with_violations}")
print("=" * 68)

if files_with_violations:
    sys.exit(2)
