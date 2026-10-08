#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
CTX = WORLD / "world_context"
STATE_PATH = CTX / "state.json"
SUMMARY_PATH = CTX / "summary.json"
EVENTS_PATH = CTX / "events.ndjson"
POLICY_PATH = CTX / "policy.json"
PROFILE_LOCAL = WORLD / "world_context_profile.json"
PROFILE_PUBLIC = ROOT / "research" / "world_context.detroit.json"
PUBLIC_CALENDARS = ROOT / "research" / "culture_calendars"
LOCAL_CALENDARS = CTX / "calendars"
MEMBERSHIP_PATH = CTX / "citizen_communities.json"
VERSION = "1.0.0"

TIME_RE = re.compile(r"Y(?P<year>\d+)-W(?P<week>\d+)-(?P<stage>[A-Za-z_]+)(?:-D(?P<day>\d+))?")
STAGE_RANK = {
    "begin": 0, "plan": 1, "before_contact": 2, "contact": 3,
    "after_contact": 4, "activity": 5, "review": 6, "settle": 7, "end": 8,
}
WEEKDAY = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}

POLICY = {
    "version": VERSION,
    "weather_is_synthetic": True,
    "weather_claim": "Synthetic simulation context, not a real forecast.",
    "culture_rule": "Never infer culture, religion, language, or holiday observance from a name, nationality, race, location, or other identity proxy.",
    "calendar_rule": "Community calendars must be explicitly enabled and provenance-backed. Maximum 50 observances per calendar pack.",
    "language_rule": "Preserve native-language names and descriptions when contributed. English is optional maintainer metadata.",
    "ranking_rule": "World League research may compare task/model behavior, never human groups or cultures.",
}

CLIMATE_PROFILES = {
    "detroit-temperate-north": {
        "label": "Detroit temperate four-season synthetic climate",
        "hemisphere": "north",
        "season_model": "meteorological",
        "weather": {
            "winter": [
                ("cold_clear", 0.40, (18, 35), 1.04, 1.10, 1.18),
                ("snow", 0.34, (16, 31), 1.28, 1.34, 1.25),
                ("winter_mix", 0.16, (24, 36), 1.36, 1.42, 1.20),
                ("cloudy", 0.10, (26, 38), 1.06, 1.08, 1.15),
            ],
            "spring": [
                ("mild", 0.42, (42, 66), 1.00, 1.00, 0.96),
                ("rain", 0.36, (39, 61), 1.13, 1.18, 0.98),
                ("storm", 0.10, (48, 68), 1.24, 1.32, 1.02),
                ("cool_clear", 0.12, (36, 58), 1.02, 1.03, 1.02),
            ],
            "summer": [
                ("clear", 0.46, (69, 86), 1.00, 1.00, 1.06),
                ("hot", 0.28, (78, 94), 1.03, 1.13, 1.30),
                ("storm", 0.18, (70, 88), 1.20, 1.30, 1.14),
                ("rain", 0.08, (67, 82), 1.10, 1.15, 1.03),
            ],
            "autumn": [
                ("clear", 0.44, (48, 70), 1.00, 1.00, 0.98),
                ("rain", 0.31, (43, 63), 1.11, 1.16, 1.00),
                ("wind", 0.15, (40, 62), 1.08, 1.15, 1.02),
                ("cold_clear", 0.10, (34, 54), 1.03, 1.05, 1.08),
            ],
        },
    }
}


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
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def stable_rng(*parts: Any) -> random.Random:
    h = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def parse_clock(raw: str) -> dict[str, Any] | None:
    m = TIME_RE.search(str(raw or ""))
    if not m:
        return None
    return {
        "raw": m.group(0),
        "year": int(m.group("year")),
        "week": int(m.group("week")),
        "stage": m.group("stage").lower(),
        "day": int(m.group("day")) if m.group("day") else None,
    }


def clock_key(raw: str) -> tuple[int, int, int, int]:
    t = parse_clock(raw)
    if not t:
        return (0, 0, 0, 0)
    return (t["year"], t["week"], t.get("day") or 0, STAGE_RANK.get(t["stage"], 3))


def tail_times(path: Path, n: int = 6) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []
    out: list[str] = []
    for line in lines:
        m = TIME_RE.search(line)
        if m:
            out.append(m.group(0))
    return out


def observed_clock() -> dict[str, Any]:
    candidates: list[str] = []
    root = WORLD / ".active_persona_view"
    if not root.exists():
        root = WORLD / "persona"
    if root.exists():
        dirs = [p for p in root.iterdir() if p.is_dir() or p.is_symlink()]
        for p in dirs[:256]:
            for fname in ("state.jsonl", "activity.jsonl", "schedule.jsonl"):
                candidates.extend(tail_times(p / fname))
    if candidates:
        raw = max(candidates, key=clock_key)
        parsed = parse_clock(raw)
        if parsed:
            return parsed
    cp = read_json(WORLD / "checkpoint.json", {})
    y = int(cp.get("year", 2045)) if isinstance(cp, dict) else 2045
    w = int(cp.get("week", 1)) if isinstance(cp, dict) else 1
    return {"raw": f"Y{y}-W{w:02d}-begin", "year": y, "week": w, "stage": "begin", "day": None}


def load_profile() -> dict[str, Any]:
    p = read_json(PROFILE_LOCAL, None)
    if not isinstance(p, dict):
        p = read_json(PROFILE_PUBLIC, {})
    if not isinstance(p, dict):
        p = {}
    p.setdefault("world_id", "detroit")
    p.setdefault("world_name", "Agentopia Detroit")
    p.setdefault("climate_profile", "detroit-temperate-north")
    p.setdefault("calendar_packs", ["us-public-civic"])
    return p


def week_dates(year: int, week: int) -> list[date]:
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError:
        monday = date(year, 1, 1) + timedelta(days=max(0, (week - 1) * 7))
    return [monday + timedelta(days=i) for i in range(7)]


def season_for(d: date, hemisphere: str = "north") -> str:
    month = d.month
    if month in (12, 1, 2):
        north = "winter"
    elif month in (3, 4, 5):
        north = "spring"
    elif month in (6, 7, 8):
        north = "summer"
    else:
        north = "autumn"
    if hemisphere.lower() != "south":
        return north
    return {"winter": "summer", "spring": "autumn", "summer": "winter", "autumn": "spring"}[north]


def weighted_choice(rng: random.Random, rows: list[tuple]) -> tuple:
    needle = rng.random()
    total = 0.0
    for row in rows:
        total += float(row[1])
        if needle <= total:
            return row
    return rows[-1]


def daily_weather(profile: dict[str, Any], d: date) -> dict[str, Any]:
    climate_id = str(profile.get("climate_profile") or "detroit-temperate-north")
    climate = CLIMATE_PROFILES.get(climate_id, CLIMATE_PROFILES["detroit-temperate-north"])
    season = season_for(d, str(climate.get("hemisphere", "north")))
    rows = climate["weather"][season]
    rng = stable_rng("world-context-weather", profile.get("world_id"), d.isoformat(), climate_id)
    condition, _weight, temp_range, transport, outdoor, energy = weighted_choice(rng, rows)
    lo, hi = temp_range
    high = rng.randint(int((lo + hi) / 2), hi)
    low = rng.randint(lo, max(lo, high - 5))
    precip = {
        "snow": rng.randint(35, 90), "winter_mix": rng.randint(40, 85),
        "rain": rng.randint(45, 90), "storm": rng.randint(55, 95),
    }.get(condition, rng.randint(0, 22))
    return {
        "date": d.isoformat(),
        "weekday": d.strftime("%A"),
        "season": season,
        "condition": condition,
        "temperature_f": {"low": low, "high": high},
        "precipitation_chance_pct": precip,
        "impacts": {
            "transport_factor": round(float(transport), 2),
            "outdoor_work_factor": round(float(outdoor), 2),
            "energy_demand_factor": round(float(energy), 2),
            "health_stress": "elevated" if condition in {"hot", "snow", "winter_mix", "storm"} else "normal",
            "public_event_disruption": condition in {"snow", "winter_mix", "storm"},
        },
        "synthetic": True,
    }


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (nth - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month, monthrange(year, month)[1])
    delta = (last.weekday() - weekday) % 7
    return last - timedelta(days=delta)


def resolve_holiday_date(rule: dict[str, Any], year: int) -> list[date]:
    kind = str(rule.get("type") or "")
    out: list[date] = []
    try:
        if kind == "fixed":
            out = [date(year, int(rule["month"]), int(rule["day"]))]
        elif kind == "nth_weekday":
            out = [nth_weekday(year, int(rule["month"]), WEEKDAY[str(rule["weekday"]).lower()], int(rule["nth"]))]
        elif kind == "last_weekday":
            out = [last_weekday(year, int(rule["month"]), WEEKDAY[str(rule["weekday"]).lower()])]
        elif kind == "explicit_dates":
            for raw in rule.get("dates", []):
                d = date.fromisoformat(str(raw))
                if d.year == year:
                    out.append(d)
    except Exception:
        return []
    if rule.get("observed_if_weekend"):
        observed: list[date] = []
        for d in out:
            if d.weekday() == 5:
                observed.append(d - timedelta(days=1))
            elif d.weekday() == 6:
                observed.append(d + timedelta(days=1))
        out += observed
    return sorted(set(out))


def load_calendar_packs(enabled: list[str]) -> list[dict[str, Any]]:
    files: dict[str, Path] = {}
    for root in (PUBLIC_CALENDARS, LOCAL_CALENDARS):
        if not root.exists():
            continue
        for p in root.glob("*.json"):
            row = read_json(p, {})
            if isinstance(row, dict) and row.get("calendar_id"):
                files[str(row["calendar_id"])] = p
    packs = []
    for cid in enabled:
        p = files.get(str(cid))
        if not p:
            continue
        row = read_json(p, {})
        if not isinstance(row, dict):
            continue
        holidays = row.get("holidays", [])
        if not isinstance(holidays, list):
            holidays = []
        row["holidays"] = holidays[:50]
        packs.append(row)
    return packs


def holidays_for_week(profile: dict[str, Any], dates: list[date]) -> list[dict[str, Any]]:
    enabled = [str(x) for x in profile.get("calendar_packs", [])]
    packs = load_calendar_packs(enabled)
    date_set = set(dates)
    out: list[dict[str, Any]] = []
    for pack in packs:
        scope = "public" if str(pack.get("calendar_type")) == "public_civic" else "community"
        for h in pack.get("holidays", [])[:50]:
            if not isinstance(h, dict):
                continue
            matches = [d for d in resolve_holiday_date(h.get("rule", {}), dates[0].year) if d in date_set]
            for d in matches:
                out.append({
                    "calendar_id": pack.get("calendar_id"),
                    "community_name": pack.get("community_name"),
                    "calendar_type": pack.get("calendar_type"),
                    "scope": scope,
                    "date": d.isoformat(),
                    "native_name": h.get("native_name") or h.get("name"),
                    "english_name": h.get("english_name") or h.get("native_name") or h.get("name"),
                    "language": h.get("language") or pack.get("language"),
                    "observance_type": h.get("observance_type", "observance"),
                    "business_effect": h.get("business_effect", "context_only"),
                    "community_effect": h.get("community_effect", "context_only"),
                    "provenance": pack.get("provenance", {}),
                })
    return sorted(out, key=lambda x: (x["date"], str(x.get("calendar_id")), str(x.get("native_name"))))


def membership_for(name: str) -> set[str]:
    data = read_json(MEMBERSHIP_PATH, {})
    if not isinstance(data, dict):
        return set()
    row = data.get(name, [])
    return {str(x) for x in row} if isinstance(row, list) else set()


def build_context(clock: dict[str, Any] | None = None) -> dict[str, Any]:
    clock = clock or observed_clock()
    profile = load_profile()
    year, week = int(clock["year"]), int(clock["week"])
    dates = week_dates(year, week)
    day_num = int(clock.get("day") or 1)
    day_num = max(1, min(7, day_num))
    today = dates[day_num - 1]
    climate_id = str(profile.get("climate_profile"))
    climate = CLIMATE_PROFILES.get(climate_id, CLIMATE_PROFILES["detroit-temperate-north"])
    weather = [daily_weather(profile, d) for d in dates]
    current_weather = weather[day_num - 1]
    holidays = holidays_for_week(profile, dates)
    current_holidays = [h for h in holidays if h["date"] == today.isoformat()]
    packs = load_calendar_packs([str(x) for x in profile.get("calendar_packs", [])])
    return {
        "version": VERSION,
        "updated_at": utc_now(),
        "world_id": profile.get("world_id"),
        "world_name": profile.get("world_name"),
        "engine_time": clock.get("raw"),
        "world_year": year,
        "world_week": week,
        "world_day": day_num,
        "calendar_week": {
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
            "today": today.isoformat(),
            "today_label": today.strftime("%A, %B %d, %Y"),
        },
        "season": {
            "name": current_weather["season"],
            "hemisphere": climate.get("hemisphere"),
            "climate_profile": climate_id,
            "climate_label": climate.get("label"),
        },
        "weather": current_weather,
        "daily_weather": weather,
        "holidays_today": current_holidays,
        "holidays_this_week": holidays,
        "calendar_packs": [{
            "calendar_id": p.get("calendar_id"),
            "community_name": p.get("community_name"),
            "calendar_type": p.get("calendar_type"),
            "language": p.get("language"),
            "holiday_count": len(p.get("holidays", [])),
            "provenance": p.get("provenance", {}),
        } for p in packs],
        "research": {
            "synthetic_weather": True,
            "culture_inference": False,
            "max_holidays_per_calendar": 50,
            "native_language_preserved": True,
            "task_context_fields": [
                "weather", "season", "holiday_or_observance", "language",
                "occupation", "domain", "regional_workflow",
            ],
        },
        "policy": POLICY,
    }


def refresh(clock: dict[str, Any] | None = None, append_event: bool = False) -> dict[str, Any]:
    CTX.mkdir(parents=True, exist_ok=True)
    write_json(POLICY_PATH, POLICY)
    summary = build_context(clock)
    old = read_json(SUMMARY_PATH, {})
    old_key = (old.get("engine_time"), old.get("calendar_week", {}).get("today")) if isinstance(old, dict) else None
    new_key = (summary.get("engine_time"), summary.get("calendar_week", {}).get("today"))
    write_json(SUMMARY_PATH, summary)
    state = read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.update({
        "version": VERSION,
        "last_engine_time": summary.get("engine_time"),
        "last_world_year": summary.get("world_year"),
        "last_world_week": summary.get("world_week"),
        "last_world_day": summary.get("world_day"),
        "updated_at": summary.get("updated_at"),
    })
    write_json(STATE_PATH, state)
    if append_event and old_key != new_key:
        append_jsonl(EVENTS_PATH, {
            "time": utc_now(),
            "event": "world_context_changed",
            "engine_time": summary.get("engine_time"),
            "season": summary.get("season", {}).get("name"),
            "weather": summary.get("weather", {}).get("condition"),
            "holidays": [h.get("english_name") for h in summary.get("holidays_today", [])],
        })
    return summary


def world_context_text(name: str = "") -> str:
    summary = read_json(SUMMARY_PATH, {})
    if not isinstance(summary, dict) or not summary:
        summary = refresh()
    weather = summary.get("weather", {})
    cal = summary.get("calendar_week", {})
    season = summary.get("season", {})
    memberships = membership_for(name) if name else set()
    relevant = []
    for h in summary.get("holidays_this_week", []):
        if h.get("scope") == "public" or h.get("calendar_id") in memberships:
            relevant.append(h)
    lines = [
        f"## Agentopia World Context v{VERSION}",
        f"- Simulation date: {cal.get('today_label', 'unknown')} ({summary.get('engine_time', '')}).",
        f"- Season: {season.get('name', 'unknown')} ({season.get('hemisphere', 'unknown')} hemisphere; synthetic climate profile: {season.get('climate_label', 'unknown')}).",
        f"- Weather today: {str(weather.get('condition', 'unknown')).replace('_', ' ')}; low {weather.get('temperature_f', {}).get('low', '?')}F / high {weather.get('temperature_f', {}).get('high', '?')}F; precipitation chance {weather.get('precipitation_chance_pct', '?')}%. This is simulated context, not a real forecast.",
        f"- Weather impacts: transport x{weather.get('impacts', {}).get('transport_factor', 1.0)}, outdoor-work x{weather.get('impacts', {}).get('outdoor_work_factor', 1.0)}, energy-demand x{weather.get('impacts', {}).get('energy_demand_factor', 1.0)}.",
    ]
    if relevant:
        labels = ", ".join(f"{h.get('native_name')} ({h.get('date')})" for h in relevant[:8])
        lines.append(f"- Relevant public/explicitly assigned observances this week: {labels}.")
    else:
        lines.append("- No public or explicitly assigned observance applies to this citizen this week.")
    lines += [
        "- Do not assume a citizen observes a cultural or religious holiday unless that community calendar is explicitly assigned or the observance is a world-level public/civic calendar.",
        "- Use weather, season and calendar context only when it materially changes the task, schedule, travel, business, health, school, public event or decision.",
    ]
    return "\n".join(lines)


def week_start(world: Any) -> None:
    t = world.clock.get_time()
    raw = str(t)
    parsed = parse_clock(raw) or {
        "raw": raw,
        "year": int(getattr(t, "year", 2045)),
        "week": int(getattr(t, "week", 1)),
        "stage": str(getattr(t, "stage", "begin")),
        "day": int(getattr(t, "day", 1) or 1),
    }
    summary = refresh(parsed, append_event=True)
    try:
        world.logger.info(
            "[CTX100] world context %s season=%s weather=%s holidays=%d",
            summary.get("engine_time"),
            summary.get("season", {}).get("name"),
            summary.get("weather", {}).get("condition"),
            len(summary.get("holidays_this_week", [])),
        )
    except Exception:
        pass


def apply_runtime_patches() -> None:
    refresh()
    from src.agents.data_manager import DataManager
    from src.world.world import World

    if not getattr(DataManager.character_prompt, "_agentopia_world_context_v100", False):
        original_prompt = DataManager.character_prompt

        def context_prompt(self):
            base = original_prompt(self)
            try:
                return str(base) + "\n\n" + world_context_text(self.char)
            except Exception:
                return base

        context_prompt._agentopia_world_context_v100 = True
        DataManager.character_prompt = context_prompt

    if not getattr(World._before_week_start, "_agentopia_world_context_v100", False):
        original_before = World._before_week_start

        def context_before(self):
            original_before(self)
            try:
                week_start(self)
            except Exception as exc:
                try:
                    self.logger.warning("[CTX100] world context week failed: %s", exc)
                except Exception:
                    pass

        context_before._agentopia_world_context_v100 = True
        World._before_week_start = context_before


def status() -> None:
    s = refresh()
    print(f"Agentopia World Context v{VERSION}")
    print("Engine time:", s.get("engine_time"))
    print("Date:", s.get("calendar_week", {}).get("today_label"))
    print("Season:", s.get("season", {}).get("name"))
    print("Weather:", s.get("weather", {}).get("condition"), s.get("weather", {}).get("temperature_f"))
    print("Holiday packs:", len(s.get("calendar_packs", [])), "Holidays this week:", len(s.get("holidays_this_week", [])))
    print("Culture inference: OFF; community calendars must be explicit and provenance-backed.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["init", "status", "refresh"], nargs="?", default="status")
    args = ap.parse_args()
    if args.command in {"init", "refresh"}:
        refresh(append_event=True)
    status()
