#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from collections import defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

TIME_RE = re.compile(r"Y(?P<year>\d+)-W(?P<week>\d+)-(?P<stage>[A-Za-z_]+)(?:-D(?P<day>\d+))?")
RUN_RE = re.compile(r".+_\d{6,}$")

DEFAULT_LOCATIONS = [
    ("Homes", "Private life, rest, reflection"),
    ("Work Hub", "Jobs, projects, income"),
    ("Cafe", "Conversation, meals, dates"),
    ("Park", "Exercise, chance encounters"),
    ("Community Hall", "Events, groups, debates"),
    ("Market", "Shopping, resources, economy"),
    ("School", "Learning and teaching"),
    ("Transit", "Moving between activities"),
]


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def tail_jsonl(path: Path, limit: int = 50) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        # JSONL files are append-only; reading the tail avoids scanning years of history.
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            chunk = 8192
            buf = b""
            while end > 0 and buf.count(b"\n") <= limit + 2:
                take = min(chunk, end)
                end -= take
                f.seek(end)
                buf = f.read(take) + buf
        rows: list[dict[str, Any]] = []
        for raw in buf.decode("utf-8", errors="replace").splitlines()[-(limit + 3):]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    rows.append(obj)
            except json.JSONDecodeError:
                # Ignore a partially written final line while Agentopia is still appending.
                continue
        return rows[-limit:]
    except Exception:
        return []


def pick_text(obj: Any, keys: Iterable[str]) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def flatten_find(obj: Any, wanted: set[str]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in wanted and lk not in found:
                found[lk] = v
            nested = flatten_find(v, wanted - set(found))
            found.update({k2: v2 for k2, v2 in nested.items() if k2 not in found})
    elif isinstance(obj, list):
        for item in obj:
            nested = flatten_find(item, wanted - set(found))
            found.update({k2: v2 for k2, v2 in nested.items() if k2 not in found})
    return found


def initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if not parts:
        return "AI"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def stable_bucket(text: str, mod: int = 12) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16) % mod


def parse_time(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    m = TIME_RE.search(value)
    if not m:
        return None
    return {
        "raw": m.group(0),
        "year": int(m.group("year")),
        "week": int(m.group("week")),
        "stage": m.group("stage").lower(),
        "day": int(m.group("day")) if m.group("day") else None,
    }


def time_sort_key(value: Any) -> tuple[int, int, int, int]:
    t = parse_time(value)
    if not t:
        return (0, 0, 0, 0)
    stage_rank = {"begin": 0, "before_contact": 1, "contact": 2, "activity": 3, "review": 4, "end": 5}
    return (t["year"], t["week"], t["day"] or 0, stage_rank.get(t["stage"], 2))


def latest_profile(agent_dir: Path) -> dict[str, Any]:
    pdir = agent_dir / "profile"
    files = sorted(pdir.glob("year=*.json"), key=lambda p: p.name) if pdir.exists() else []
    return read_json(files[-1], {}) if files else {}


def latest_state(agent_dir: Path) -> tuple[dict[str, Any], str]:
    rows = tail_jsonl(agent_dir / "state.jsonl", 8)
    if not rows:
        return {}, ""
    row = rows[-1]
    content = row.get("content", row)
    return (content if isinstance(content, dict) else {}), str(row.get("time", ""))


def latest_schedule(agent_dir: Path) -> dict[str, Any]:
    rows = tail_jsonl(agent_dir / "schedule.jsonl", 120)
    valid = [r for r in rows if r.get("status", "created") == "created"]
    if not valid:
        return {}
    # This is only the newest schedule record written, not necessarily what is
    # happening now. Current-day selection is handled by schedule_for_time().
    return max(valid, key=lambda r: time_sort_key(r.get("time") or r.get("activity_time")))


def schedule_for_time(agent_dir: Path, current_time: str) -> dict[str, Any]:
    now = parse_time(current_time)
    if not now or not now.get("day"):
        return {}
    rows = tail_jsonl(agent_dir / "schedule.jsonl", 240)
    matches = []
    priority = {"encounter": 0, "public": 1, "joint": 2, "solo": 0}
    for r in rows:
        if r.get("status", "created") != "created":
            continue
        at = parse_time(r.get("activity_time"))
        if not at:
            continue
        if (at["year"], at["week"], at.get("day")) == (now["year"], now["week"], now.get("day")):
            matches.append(r)
    if not matches:
        return {}
    return max(matches, key=lambda r: (priority.get(str(r.get("type", "")), 0), time_sort_key(r.get("time"))))


def phase_activity(current_time: str, schedule: dict[str, Any], activity: dict[str, Any]) -> str:
    now = parse_time(current_time) or {}
    stage = str(now.get("stage") or "").lower()
    if stage == "activity":
        if schedule.get("activity_name"):
            return str(schedule.get("activity_name"))
        if activity.get("content"):
            return str(activity.get("content"))
        day = now.get("day")
        return f"Daily life - Day {day}" if day else "Daily life"
    labels = {
        "begin": "Starting the week",
        "plan": "Planning goals and the week",
        "before_contact": "Reviewing events and commitments",
        "contact": "Messaging people and arranging plans",
        "after_contact": "Finalizing social plans",
        "review": "Reflecting on the week",
        "end": "Closing the week",
    }
    return labels.get(stage, "Waiting for the next simulation step")


def latest_activity(agent_dir: Path) -> dict[str, Any]:
    rows = tail_jsonl(agent_dir / "activity.jsonl", 40)
    return rows[-1] if rows else {}


def contact_messages(agent_name: str, agent_dir: Path) -> list[dict[str, Any]]:
    cdir = agent_dir / "contact"
    if not cdir.exists():
        return []
    out: list[dict[str, Any]] = []
    for f in cdir.glob("*.jsonl"):
        if f.name == "sig.jsonl":
            continue
        peer = f.stem
        for row in tail_jsonl(f, 6):
            content = pick_text(row, ("content", "message", "text", "body", "utterance", "msg"))
            if not content:
                nested = flatten_find(row, {"content", "message", "text", "body", "utterance"})
                for v in nested.values():
                    if isinstance(v, str) and v.strip():
                        content = v.strip()
                        break
            sender = pick_text(row, ("sender", "from", "from_char", "source", "agent_name"))
            recipient = pick_text(row, ("recipient", "to", "to_char", "target"))
            direction = str(row.get("direction", "")).lower()
            if not sender:
                sender = peer if direction in {"in", "inbound", "received"} else agent_name
            if not recipient:
                recipient = agent_name if sender == peer else peer
            if content:
                out.append({
                    "time": str(row.get("time", "")),
                    "sender": sender,
                    "recipient": recipient,
                    "content": content[:800],
                    "peer": peer,
                })
    out.sort(key=lambda x: time_sort_key(x.get("time")))
    return out[-80:]


def character_memories(agent_dir: Path) -> list[dict[str, Any]]:
    cdir = agent_dir / "memory" / "scratchpad" / "characters"
    if not cdir.exists():
        return []
    items: list[dict[str, Any]] = []
    for f in cdir.glob("*.jsonl"):
        rows = tail_jsonl(f, 3)
        if not rows:
            continue
        row = rows[-1]
        text = pick_text(row, ("summary", "content", "reflection", "note"))
        if text:
            items.append({"person": f.stem, "summary": text[:1000], "time": str(row.get("time", ""))})
    return sorted(items, key=lambda x: x["person"].lower())




def normalize_gender(profile: dict[str, Any]) -> dict[str, str]:
    """Return visual gender metadata from the explicit profile field only.

    Never infer gender from a name. Unknown/non-binary/unspecified values use
    the neutral figure so the observer does not invent identity data.
    """
    raw = str(profile.get("gender") or "").strip() if isinstance(profile, dict) else ""
    key = raw.casefold().replace("_", "-").replace(" ", "-")
    feminine = {"female", "f", "woman", "girl", "feminine"}
    masculine = {"male", "m", "man", "boy", "masculine"}
    if key in feminine:
        return {"raw": raw or "Female", "presentation": "feminine", "symbol": "♀"}
    if key in masculine:
        return {"raw": raw or "Male", "presentation": "masculine", "symbol": "♂"}
    return {"raw": raw or "Unspecified", "presentation": "neutral", "symbol": "•"}

def profile_job(profile: dict[str, Any]) -> str:
    pos = profile.get("position") if isinstance(profile, dict) else None
    if isinstance(pos, dict):
        role = str(pos.get("role") or "").strip()
        org = str(pos.get("organization") or "").strip()
        if role and org:
            return f"{role} @ {org}"
        return role or org or "Resident"
    return "Resident"


def profile_intro(profile: dict[str, Any]) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("brief_introduction") or profile.get("details") or "")[:600]


def infer_location(schedule: dict[str, Any], activity: dict[str, Any], profile: dict[str, Any], agent_name: str = "") -> str:
    explicit = str(schedule.get("location") or "").strip()
    if explicit:
        return explicit
    text = " ".join([
        str(schedule.get("activity_name") or ""),
        str(activity.get("content") or ""),
        str((activity.get("outcome") or {}).get("outcome") if isinstance(activity.get("outcome"), dict) else ""),
    ]).lower()
    rules = [
        (("work", "job", "office", "shift", "project"), "Work Hub"),
        (("cafe", "coffee", "restaurant", "dinner", "lunch", "breakfast", "meal", "date"), "Cafe"),
        (("park", "walk", "run", "exercise", "jog", "garden"), "Park"),
        (("shop", "market", "buy", "store", "grocer"), "Market"),
        (("school", "class", "study", "lecture", "teach", "library"), "School"),
        (("community", "meeting", "club", "event", "debate", "party"), "Community Hall"),
    ]
    for needles, label in rules:
        if any(n in text for n in needles):
            return label
    return "Homes"


def normalized_state(state: dict[str, Any]) -> dict[str, Any]:
    f = state.get("fulfillment", {}) if isinstance(state.get("fulfillment"), dict) else {}
    assets = state.get("assets", {}) if isinstance(state.get("assets"), dict) else {}
    skills = state.get("skills", {}) if isinstance(state.get("skills"), dict) else {}
    def num(v: Any, default: int = 0) -> int | float:
        return v if isinstance(v, (int, float)) else default
    return {
        "vitality": num(state.get("vitality"), 50),
        "mood": num(f.get("mood"), 50),
        "social": num(f.get("social"), 50),
        "esteem": num(f.get("esteem"), 50),
        "material": num(f.get("material"), 50),
        "deposit": num(assets.get("deposit"), 0),
        "possessions": assets.get("possessions", []) if isinstance(assets.get("possessions", []), list) else [],
        "skills": skills,
    }




# AGENTOPIA_ACTIVITY_STREAM_V143
def activity_stream_messages(owner: str, a_dir: Path) -> list[dict[str, Any]]:
    """Expose persisted joint/public activity participation in the same live stream as contacts."""
    rows = tail_jsonl(a_dir / "activity.jsonl", 30)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        typ = str(row.get("type") or "")
        if typ not in {"joint", "public"}:
            continue
        activity_name = str(row.get("activity_name") or "Activity")
        content = str(row.get("summary") or row.get("participation") or row.get("reflection") or "").strip()
        if not content:
            continue
        participants = [str(x) for x in (row.get("participants") or []) if str(x) and str(x) != owner]
        recipient = "Group: " + ", ".join(participants[:6]) if participants else activity_name
        out.append({
            "time": str(row.get("time") or ""),
            "sender": owner,
            "recipient": recipient,
            "content": f"[{typ.title()} • {activity_name}] {content}",
            "stream_type": "activity",
        })
    return out

# AGENTOPIA_SOCIAL_TELEMETRY_V145_START
def v145_model_pools() -> list[dict[str, Any]]:
    import json as _json
    import urllib.request as _ur
    specs = [
        ("SOCIAL 350M", 8084, 48),
        ("CITIZEN 1.2B", 8081, 32),
        ("STRATEGY 2.6B", 8082, 8),
        ("CYBER 7B", 8083, 6),
    ]
    out = []
    for name, port, configured in specs:
        try:
            with _ur.urlopen(f"http://127.0.0.1:{port}/slots", timeout=0.45) as r:
                rows = _json.loads(r.read().decode("utf-8"))
            busy = sum(1 for x in rows if isinstance(x, dict) and x.get("is_processing"))
            out.append({"name": name, "port": port, "busy": busy, "total": len(rows), "configured": configured, "online": True})
        except Exception:
            out.append({"name": name, "port": port, "busy": 0, "total": configured, "configured": configured, "online": False})
    return out


def v145_message_body(content: str) -> str:
    import ast as _ast
    import re as _re
    text = str(content or "")
    m = _re.search(r"\bmessage\s*=\s*(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')", text, _re.S)
    if m:
        try:
            return str(_ast.literal_eval(m.group(1))).strip()
        except Exception:
            pass
    return text.strip()


def v145_group_broadcasts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import ast as _ast
    import re as _re
    out=[]; seen=set()
    for original in messages:
        m=dict(original)
        content=str(m.get("content") or "")
        if content.lstrip().startswith("propose_joint_activity("):
            # The same proposal is persisted once per invitee. Render it once as a group broadcast.
            key=(m.get("time"), m.get("sender"), content)
            if key in seen:
                continue
            seen.add(key)
            mm=_re.search(r"invited_persons\s*=\s*(\[[^\]]*\])", content, _re.S)
            if mm:
                try:
                    invited=_ast.literal_eval(mm.group(1))
                    if isinstance(invited,list) and invited:
                        m["recipient"]="Group: "+", ".join(str(x) for x in invited[:8])
                except Exception:
                    pass
        out.append(m)
    return out


def v145_conversation_quality(messages: list[dict[str, Any]]) -> dict[str, Any]:
    import re as _re
    if not messages:
        return {"messages":0,"current_slot_messages":0,"unique_speakers":0,"unique_pairs":0,"repeat_pct":0.0,"current_time":""}
    latest=max((str(m.get("time") or "") for m in messages), key=time_sort_key)
    cur=[m for m in messages if str(m.get("time") or "")==latest]
    sample=cur or messages
    speakers={str(m.get("sender") or "") for m in sample if str(m.get("sender") or "")}
    pairs={tuple(sorted((str(m.get("sender") or ""),str(m.get("recipient") or "")))) for m in sample}
    bodies=[]
    for m in sample:
        body=v145_message_body(str(m.get("content") or "")).lower()
        body=_re.sub(r"\s+"," ",body).strip()
        if body: bodies.append(body)
    counts={}
    for b in bodies: counts[b]=counts.get(b,0)+1
    repeats=sum(max(0,n-1) for n in counts.values())
    pct=round((repeats/max(1,len(bodies)))*100.0,1)
    return {
        "messages":len(messages),
        "current_slot_messages":len(cur),
        "unique_speakers":len(speakers),
        "unique_pairs":len(pairs),
        "repeat_pct":pct,
        "current_time":latest,
    }
# AGENTOPIA_SOCIAL_TELEMETRY_V145_END

class WorldReader:
    def __init__(self, agentopia_root: Path):
        self.root = agentopia_root.resolve()
        self.data_root = self.root / "data"

    def _run_activity_mtime(self, run_dir: Path) -> float:
        """Return the newest relevant write time inside a run.

        Agentopia appends state, schedules, activities and contacts while the
        simulation is running. Directory mtimes do not reliably change when
        existing files are appended, so the observer must inspect the files.
        """
        latest = 0.0
        try:
            latest = run_dir.stat().st_mtime
        except OSError:
            pass

        for name in ("checkpoint.json", "public_events.jsonl", "faction_events.jsonl", "factions.json", "config.json"):
            path = run_dir / name
            try:
                if path.exists():
                    latest = max(latest, path.stat().st_mtime)
            except OSError:
                pass

        persona_root = run_dir / "persona"
        if persona_root.exists():
            for agent_dir in persona_root.iterdir():
                if not agent_dir.is_dir():
                    continue
                for name in ("state.jsonl", "schedule.jsonl", "activity.jsonl", "reward.jsonl"):
                    path = agent_dir / name
                    try:
                        if path.exists():
                            latest = max(latest, path.stat().st_mtime)
                    except OSError:
                        pass
                contact_dir = agent_dir / "contact"
                if contact_dir.exists():
                    for path in contact_dir.glob("*.jsonl"):
                        try:
                            latest = max(latest, path.stat().st_mtime)
                        except OSError:
                            pass
        return latest

    def runs(self) -> list[dict[str, Any]]:
        if not self.data_root.exists():
            return []
        rows = []
        for d in self.data_root.iterdir():
            if not d.is_dir() or not (d / "persona").exists() or d.name == "persona_template":
                continue
            try:
                mtime = d.stat().st_mtime
            except OSError:
                mtime = 0
            generated = bool(
                RUN_RE.match(d.name)
                or (d / "checkpoint.json").exists()
                or (d / "config.json").exists()
            )
            activity_mtime = self._run_activity_mtime(d)
            rows.append({
                "name": d.name,
                "mtime": mtime,
                "activity_mtime": activity_mtime,
                "generated": generated,
            })
        rows.sort(key=lambda r: (r["generated"], r["activity_mtime"], r["mtime"]), reverse=True)
        active_name = next((r["name"] for r in rows if r["generated"]), None)
        for row in rows:
            row["active"] = row["name"] == active_name
        return rows

    def pick_run(self, requested: str | None = None) -> Path | None:
        if not requested:
            persistent = self.data_root / "detroit_persistent"
            if persistent.is_dir() and (persistent / "persona").exists():
                return persistent
        if requested:
            candidate = (self.data_root / requested).resolve()
            if self.data_root.resolve() in candidate.parents and candidate.is_dir() and (candidate / "persona").exists():
                return candidate
        rows = self.runs()
        generated = [r for r in rows if r["generated"]]
        if generated:
            return self.data_root / generated[0]["name"]
        return None

    def _process_running(self) -> bool:
        try:
            hb = self.root / "runtime" / "engine_heartbeat.json"
            if hb.exists() and (time.time() - hb.stat().st_mtime) < 20:
                return True
        except Exception:
            pass
        for pattern in ("scripts/run_detroit_persistent.py", "run_detroit_persistent.py"):
            try:
                cp = subprocess.run(
                    ["pgrep", "-f", pattern],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.5,
                )
                if cp.returncode == 0 and bool(cp.stdout.strip()):
                    return True
            except Exception:
                pass
        return False

    def _boot_state(self) -> tuple[str, float | None]:
        path = self.root / "runtime" / "boot_state"
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip().split(None, 1)
            if not raw:
                return "", None
            stamp = float(raw[0])
            phase = raw[1] if len(raw) > 1 else ""
            return phase, max(0.0, time.time() - stamp)
        except Exception:
            return "", None

    def _last_write(self, run_dir: Path) -> tuple[float, str]:
        newest = 0.0
        newest_path = ""
        candidates = [run_dir / "checkpoint.json", run_dir / "public_events.jsonl", run_dir / "faction_events.jsonl", run_dir / "factions.json", run_dir / "locations.json", run_dir / "positions.json"]
        persona = run_dir / "persona"
        if persona.exists():
            for agent in persona.iterdir():
                if not agent.is_dir():
                    continue
                candidates.extend(agent / n for n in ("state.jsonl", "schedule.jsonl", "activity.jsonl", "reward.jsonl"))
                cdir = agent / "contact"
                if cdir.exists():
                    candidates.extend(cdir.glob("*.jsonl"))
        for path in candidates:
            try:
                mt = path.stat().st_mtime
            except OSError:
                continue
            if mt > newest:
                newest = mt
                try:
                    newest_path = str(path.relative_to(run_dir))
                except Exception:
                    newest_path = str(path)
        return newest, newest_path

    def _log_tail(self, run: Path, limit: int = 14) -> list[str]:
        candidates = [
            self.root / "logs" / run.name / "world.log",
            self.root / "live_world" / "agentopia-simulation.log",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                return [x[-500:] for x in lines[-limit:] if x.strip()]
            except Exception:
                pass
        return []

    def snapshot(self, requested: str | None = None) -> dict[str, Any]:
        # requested='auto' intentionally follows the most recently changing run.
        if requested == "auto":
            requested = None
        run = self.pick_run(requested)
        if run is None:
            return {
                "ok": False,
                "error": f"No generated Agentopia run found under {self.data_root}",
                "agentopia_root": str(self.root),
                "runs": self.runs(),
                "engine": {"process_running": self._process_running(), "phase": "initializing"},
            }

        persona_root = run / "persona"
        all_agent_dirs = sorted([p for p in persona_root.iterdir() if p.is_dir()], key=lambda p: p.name.lower())
        background_dirs = [p for p in all_agent_dirs if (p / "_background.json").exists()]
        agent_dirs = [p for p in all_agent_dirs if not (p / "_background.json").exists()]

        # First pass: determine the simulation's actually observed clock.  Do NOT
        # use activity_time from schedules because schedules can be weeks ahead.
        observed_times: list[str] = []
        raw: dict[str, dict[str, Any]] = {}
        all_messages: list[dict[str, Any]] = []
        for a_dir in agent_dirs:
            name = a_dir.name
            state_raw, state_time = latest_state(a_dir)
            schedule_written = latest_schedule(a_dir)
            activity = latest_activity(a_dir)
            msgs = contact_messages(name, a_dir)

            msgs = list(msgs) + activity_stream_messages(name, a_dir)
            raw[name] = {
                "dir": a_dir,
                "profile": latest_profile(a_dir),
                "state": state_raw,
                "state_time": state_time,
                "schedule_written": schedule_written,
                "activity": activity,
                "messages": msgs,
                "memories": character_memories(a_dir),
            }
            all_messages.extend(msgs)
            for val in (state_time, schedule_written.get("time"), activity.get("time")):
                if isinstance(val, str) and parse_time(val):
                    observed_times.append(val)
            for m in msgs[-8:]:
                val = m.get("time")
                if isinstance(val, str) and parse_time(val):
                    observed_times.append(val)

        events = tail_jsonl(run / "public_events.jsonl", 30)
        faction_events = tail_jsonl(run / "faction_events.jsonl", 30)
        for fe in faction_events:
            kind = str(fe.get("kind") or "Faction update").replace("_", " ").title()
            faction_name = str(fe.get("faction_name") or fe.get("faction") or "Agentopia factions")
            if fe.get("kind") == "recruited":
                desc = f"{faction_name} recruited {fe.get('member', 'a citizen')} • membership {fe.get('member_count', '?')}"
            elif fe.get("kind") == "population_expansion":
                desc = f"{faction_name} reached the recruitment threshold. +{fe.get('added', 0)} new citizens entered Agentopia."
            else:
                desc = str(fe.get("member") or fe.get("candidate") or "Faction state changed")
            events.append({
                "time": str(fe.get("time") or ""),
                "event_name": kind,
                "description": desc,
                "faction_event": True,
            })
        events.sort(key=lambda e: time_sort_key(e.get("time")))
        events = events[-30:]
        faction_state = read_json(run / "factions.json", {})
        for evt in events[-10:]:
            val = evt.get("time")
            if isinstance(val, str) and parse_time(val):
                observed_times.append(val)

        current_time = max(observed_times, key=time_sort_key) if observed_times else ""
        checkpoint = read_json(run / "checkpoint.json", {})
        if not current_time and isinstance(checkpoint, dict):
            y, w = checkpoint.get("year"), checkpoint.get("week")
            if isinstance(y, int) and isinstance(w, int):
                current_time = f"Y{y}-W{w:02d}-begin"

        agents: list[dict[str, Any]] = []
        relationship_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        for name, item in raw.items():
            a_dir = item["dir"]
            profile = item["profile"]
            activity = item["activity"]
            msgs = item["messages"]
            for m in msgs:
                pair = tuple(sorted((m["sender"], m["recipient"])))
                relationship_counts[pair] += 1

            today_schedule = schedule_for_time(a_dir, current_time)
            now = parse_time(current_time) or {}
            faction = profile.get("faction", {}) if isinstance(profile.get("faction"), dict) else {}
            faction_id = str(faction.get("id") or "")
            hq_by_faction = {
                "thai_guardians": "faction/thai_guardians_hq",
                "obsidian_network": "faction/obsidian_network_hq",
            }
            explicit_location = str(today_schedule.get("location") or "").strip()

            # A real scheduled activity always wins. Otherwise faction members
            # operate from their HQ and neutral citizens return to their own homes.
            if now.get("stage") == "activity" and explicit_location:
                location = explicit_location
            elif faction_id in hq_by_faction:
                location = hq_by_faction[faction_id]
            elif now.get("stage") == "activity":
                location = infer_location(today_schedule, activity, profile, name)
            else:
                location = f"home/{name}"
            action_text = phase_activity(current_time, today_schedule, activity)
            outcome = ""
            if isinstance(activity.get("outcome"), dict):
                outcome = str(activity["outcome"].get("outcome") or "")

            gender_meta = normalize_gender(profile)
            agents.append({
                "name": name,
                "initials": initials(name),
                "color_index": stable_bucket(name),
                "gender": gender_meta["raw"],
                "gender_presentation": gender_meta["presentation"],
                "gender_symbol": gender_meta["symbol"],
                "faction": faction,
                "founder_id": profile.get("founder_id", ""),
                "founding_citizen": bool(profile.get("founding_citizen", False)),
                "lineage": profile.get("lineage", {}) if isinstance(profile.get("lineage"), dict) else {},
                "origin": profile.get("origin", {}) if isinstance(profile.get("origin"), dict) else {},
                "job": profile_job(profile),
                "intro": profile_intro(profile),
                "location": location,
                "activity": action_text[:240],
                "activity_type": str(today_schedule.get("type") or activity.get("type") or now.get("stage") or "unknown"),
                "activity_time": str(today_schedule.get("activity_time") or current_time or activity.get("time") or ""),
                "outcome": outcome[:500],
                "state": normalized_state(item["state"]),
                "memories": item["memories"][:20],
                "last_message": msgs[-1] if msgs else None,
                "profile": {
                    "core_motivation": profile.get("core_motivation", ""),
                    "values": profile.get("values", ""),
                    "conflicts": profile.get("conflicts", ""),
                    "preferences": profile.get("preferences", ""),
                },
            })

        # Deduplicate messages because both sides persist the same exchange.
        seen = set()
        messages = []
        for m in sorted(all_messages, key=lambda x: time_sort_key(x.get("time"))):
            key = (m.get("time"), m.get("sender"), m.get("recipient"), m.get("content"))
            if key in seen:
                continue
            seen.add(key)
            messages.append(m)
        messages = messages[-120:]
        # AGENTOPIA_SOCIAL_TELEMETRY_V145_APPLY
        messages = v145_group_broadcasts(messages)
        conversation_quality = v145_conversation_quality(messages)

        # Locations: Agentopia schema is {"public": {...}, "private": {...}}.
        # Return the complete location catalog so every house/building can open
        # an Interior View. The Neighborhood renderer decides which cards to show.
        locations_json = read_json(run / "locations.json", {})
        catalog: dict[str, dict[str, Any]] = {}

        def add_location(key: Any, meta: Any, kind: str = "public") -> None:
            name = str(key or "").strip()
            if not name:
                return
            data = meta if isinstance(meta, dict) else {}
            catalog[name] = {
                "name": name,
                "display_name": str(data.get("display_name") or name),
                "kind": str(data.get("kind") or kind),
                "owner": str(data.get("owner") or ""),
                "size": str(data.get("size") or "medium"),
                "description": str(data.get("description") or "").strip(),
                "objects": [str(x) for x in (data.get("objects") or []) if str(x).strip()][:16],
                "faction_id": str(data.get("faction_id") or ""),
            }

        if isinstance(locations_json, dict) and ("public" in locations_json or "private" in locations_json):
            for kind in ("public", "private"):
                group = locations_json.get(kind, {})
                if isinstance(group, dict):
                    for key, meta in group.items():
                        add_location(key, meta, kind)
        elif isinstance(locations_json, dict):
            # Backward-compatible observer/world formats.
            candidates = locations_json.get("locations", locations_json)
            if isinstance(candidates, dict):
                for key, meta in candidates.items():
                    data = meta if isinstance(meta, dict) else {}
                    add_location(key, data, str(data.get("kind") or "public"))
            elif isinstance(candidates, list):
                for row in candidates:
                    if not isinstance(row, dict):
                        continue
                    name = row.get("name") or row.get("location") or row.get("id")
                    if name:
                        add_location(name, row, str(row.get("kind") or "public"))

        occupied_names: defaultdict[str, list[str]] = defaultdict(list)
        for citizen in agents:
            loc = str(citizen.get("location") or "").strip()
            if not loc:
                continue
            occupied_names[loc].append(str(citizen.get("name") or ""))
            if loc not in catalog:
                kind = "private" if loc.startswith("home/") else "derived"
                owner = loc.split("/", 1)[1] if loc.startswith("home/") and "/" in loc else ""
                add_location(
                    loc,
                    {
                        "display_name": f"{owner}'s Home" if owner else loc,
                        "owner": owner,
                        "size": "small" if kind == "private" else "medium",
                    },
                    kind,
                )

        if not catalog:
            for name, description in DEFAULT_LOCATIONS:
                add_location(name, {"display_name": name, "description": description}, "public")

        # Faction headquarters are first-class buildings. They are included even
        # if the current run was created before the HQ update.
        hq_meta = {
            "thai_guardians": {
                "key": "faction/thai_guardians_hq",
                "display_name": "ThAI Guardians HQ",
                "leader": "TGOT",
                "description": "Detroit command center for the ThAI Guardians: defense, mentoring, training, local AI operations and civic protection.",
            },
            "obsidian_network": {
                "key": "faction/obsidian_network_hq",
                "display_name": "Obsidian Network HQ",
                "leader": "Morbeious",
                "description": "Dark Detroit command center for the fictional Obsidian Network: internal strategy, research, recruiting and intelligence analysis.",
            },
        }
        state_factions = faction_state.get("factions", {}) if isinstance(faction_state, dict) else {}
        for fid, meta in hq_meta.items():
            key = meta["key"]
            if key not in catalog:
                add_location(
                    key,
                    {
                        "display_name": meta["display_name"],
                        "owner": meta["leader"],
                        "size": "large",
                        "description": meta["description"],
                        "faction_id": fid,
                    },
                    "public",
                )
            faction_row = state_factions.get(fid, {}) if isinstance(state_factions, dict) else {}
            member_names = list(faction_row.get("members", [])) if isinstance(faction_row, dict) else []
            catalog[key]["hq"] = True
            catalog[key]["faction_id"] = fid
            catalog[key]["member_names"] = member_names
            catalog[key]["member_count"] = len(member_names)
            catalog[key]["display_name"] = meta["display_name"]
            if not catalog[key].get("description"):
                catalog[key]["description"] = meta["description"]

        records = list(catalog.values())
        for rec in records:
            names = occupied_names.get(str(rec.get("name") or ""), [])
            rec["occupant_names"] = names
            rec["occupied_count"] = len(names)

        # Occupied rooms and HQs first; public buildings before empty homes.
        records.sort(
            key=lambda r: (
                0 if r.get("occupied_count") else 1,
                0 if r.get("hq") else 1,
                0 if r.get("kind") == "public" else 1,
                str(r.get("display_name") or r.get("name") or "").lower(),
            )
        )
        locations = []
        seen_locs: set[str] = set()
        for rec in records:
            key = str(rec.get("name") or "")
            if not key or key in seen_locs:
                continue
            seen_locs.add(key)
            row = dict(rec)
            row["index"] = len(locations)
            locations.append(row)

        relationships = []
        max_count = max(relationship_counts.values(), default=1)
        for (a, b), count in relationship_counts.items():
            relationships.append({"a": a, "b": b, "interactions": count, "strength": round(0.15 + 0.85 * (count / max_count), 3)})
        relationships.sort(key=lambda e: e["interactions"], reverse=True)

        last_write, last_write_path = self._last_write(run)
        write_age = max(0.0, time.time() - last_write) if last_write else None
        process_running = self._process_running()
        boot_phase, boot_age = self._boot_state()
        parsed = parse_time(current_time) or {}
        stage = parsed.get("stage") or "initializing"
        booting = (not process_running and bool(boot_phase) and (boot_age is None or boot_age < 900) and (boot_phase.startswith("STARTING") or boot_phase.startswith("ENGINE_STARTING")))
        if process_running and write_age is not None and write_age < 20:
            engine_state = "live"
        elif process_running and (write_age is None or write_age < 120):
            engine_state = "thinking"
        elif process_running:
            engine_state = "waiting"
        elif booting:
            engine_state = "booting"
        else:
            engine_state = "stopped"

        detroit_history = read_json(run / "detroit_history.json", {})
        if not detroit_history:
            detroit_history = read_json(self.root / "data" / "detroit" / "detroit_history.json", {})
        founders_registry = read_json(run / "founders.json", {})
        if not founders_registry:
            founders_registry = read_json(self.root / "data" / "detroit" / "founders.json", {})
        speed_state = read_json(self.root / "data" / "simulation_speed.json", {"mode":"normal","label":"Normal","multiplier":1,"timeline_multiplier":1})
        # AGENTOPIA_COGNITION_SNAPSHOT_V130
        cognition_summary = read_json(run / "cognition" / "summary.json", {})
        # AGENTOPIA_HUMANITY_SNAPSHOT_V140
        humanity_summary = read_json(run / "humanity" / "summary.json", {})

        # AGENTOPIA_RUNTIME_ACTIVE_COUNT_V143
        runtime_view = run / ".active_persona_view"
        try:
            runtime_active_count = len([p for p in runtime_view.iterdir() if p.is_dir() or p.is_symlink()]) if runtime_view.exists() else len(agents)
        except Exception:
            runtime_active_count = len(agents)

        # AGENTOPIA_MISSION_SNAPSHOT_V160
        mission_power = read_json(run / "mission_justice" / "summary.json", {})

        # AGENTOPIA_FINANCE_SNAPSHOT_V161
        financial_network = read_json(run / "finance" / "summary.json", {})

        # AGENTOPIA_CAREER_SNAPSHOT_V1614
        career_economy = read_json(run / "career" / "summary.json", {})

        # AGENTOPIA_HUMAN_ECONOMY_SNAPSHOT_V170
        human_economy = read_json(run / "human_economy" / "summary.json", {})

        # AGENTOPIA_BUSINESS_ECONOMY_SNAPSHOT_V171
        business_economy = read_json(run / "business_economy" / "summary.json", {})

        # AGENTOPIA_RELEASE_VERSION_V172
        try:
            release_version = (self.root / "VERSION").read_text(encoding="utf-8").strip()
        except Exception:
            release_version = "1.7.4.2"

        # AGENTOPIA_EDUCATION_SKILLS_SNAPSHOT_V172
        education_skills = read_json(run / "education" / "summary.json", {})

        # AGENTOPIA_HEALTHCARE_SNAPSHOT_V173
        healthcare = read_json(run / "healthcare" / "summary.json", {})

        # AGENTOPIA_MOBILITY_SNAPSHOT_V174
        mobility_time = read_json(run / "mobility" / "summary.json", {})

        # AGENTOPIA_WORLD_CONTEXT_SNAPSHOT_V100
        world_context = read_json(run / "world_context" / "summary.json", {})

        return json_safe({
            "ok": True,
            "release_version": release_version,
            "app_version": release_version,
            "release_name": "Mobility & Time",
            "detroit_history": detroit_history,
            "founders_registry": founders_registry,
            "speed": speed_state,
            "cognition": cognition_summary,
            "humanity": humanity_summary,
            "mission_power": mission_power,
            "financial_network": financial_network,
            "career_economy": career_economy,
            "human_economy": human_economy,
            "business_economy": business_economy,
            "education_skills": education_skills,
            "healthcare": healthcare,
            "mobility_time": mobility_time,
            "world_context": world_context,
            "agentopia_root": str(self.root),
            "run": run.name,
            "runs": self.runs(),
            "run_activity_mtime": self._run_activity_mtime(run),
            "current_time": current_time,
            "current_time_parsed": parse_time(current_time),
            "agent_count": runtime_active_count,
            "runtime_active_count": runtime_active_count,
            "population_total": len(all_agent_dirs),
            "background_count": len(background_dirs),
            "factions": faction_state,
            "agents": agents,
            "locations": locations,
            "messages": messages,
            "conversation_quality": conversation_quality,
            "model_pools": v145_model_pools(),
            "relationships": relationships[:150],
            "public_events": events[-12:],
            "engine": {
                "process_running": process_running,
                "boot_state": boot_phase,
                "boot_age": round(boot_age, 1) if boot_age is not None else None,
                "state": engine_state,
                "phase": stage,
                "last_write_age": round(write_age, 1) if write_age is not None else None,
                "last_write_path": last_write_path,
                "log_tail": self._log_tail(run),
            },
            "updated_at": time.time(),
        })


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AgentopiaDetroit/1.7.4.5.1-observability-stability"

    @property
    def app(self) -> "AppServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.app.verbose:
            super().log_message(fmt, *args)

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        ctype, _ = mimetypes.guess_type(path.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/speed":
            self.send_json({"ok": False, "error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(min(length, 4096))
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        mode = str(payload.get("mode") or "normal")
        presets = {
            "slow": {"label":"Slow", "multiplier":0.5, "timeline_multiplier":0.5},
            "normal": {"label":"Normal", "multiplier":1, "timeline_multiplier":1},
            "x2": {"label":"Fast x2", "multiplier":2, "timeline_multiplier":2},
            "x5": {"label":"Faster x5", "multiplier":5, "timeline_multiplier":5},
            "x10": {"label":"Fastest x10", "multiplier":10, "timeline_multiplier":10},
            "x1000": {"label":"Ludicrous x1000", "multiplier":1000, "timeline_multiplier":1000},
        }
        if mode not in presets:
            self.send_json({"ok": False, "error": "invalid speed"}, 400)
            return
        state = {"mode": mode, **presets[mode]}
        path = self.app.reader.root / "data" / "simulation_speed.json"
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        self.send_json({"ok": True, "speed": state})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/snapshot":
            requested = query.get("run", [None])[0]
            try:
                self.send_json(self.app.reader.snapshot(requested))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 500)
            return
        if parsed.path == "/api/runs":
            self.send_json({"ok": True, "runs": self.app.reader.runs()})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "agentopia_root": str(self.app.reader.root)})
            return
        if parsed.path in {"/", "/index.html"}:
            self.serve_file(self.app.static_root / "index.html")
            return
        safe = parsed.path.lstrip("/")
        candidate = (self.app.static_root / safe).resolve()
        if self.app.static_root.resolve() not in candidate.parents:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.serve_file(candidate)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], reader: WorldReader, static_root: Path, verbose: bool = False):
        self.reader = reader
        self.static_root = static_root
        self.verbose = verbose
        super().__init__(address, AppHandler)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    default_root = script_dir.parent if (script_dir.parent / "data").exists() else Path.home() / "AI" / "Agentopia"
    ap = argparse.ArgumentParser(description="Live graphical observer for Agentopia")
    ap.add_argument("--agentopia-root", type=Path, default=default_root)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    root = args.agentopia_root.expanduser().resolve()
    if not (root / "data").exists():
        print(f"ERROR: Agentopia data directory not found: {root / 'data'}", file=sys.stderr)
        return 2

    reader = WorldReader(root)
    server = AppServer((args.host, args.port), reader, script_dir / "static", args.verbose)
    url = f"http://{args.host}:{args.port}/"
    print("=" * 62)
    print(" Agentopia Live World")
    print("=" * 62)
    print(f" Agentopia: {root}")
    print(f" Dashboard: {url}")
    print(" Read-only observer: ON")
    print(" Press Ctrl+C to stop")
    print("=" * 62)
    # AGENTOPIA_NO_AUTO_BROWSER_V17451
    # Persistent observer restarts must never spawn a new browser window.
    # OPEN-AGENTOPIA-DETROIT.command remains the intentional manual opener.
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
