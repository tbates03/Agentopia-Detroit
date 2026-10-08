#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(os.environ.get("AGENTOPIA_HOME", str(Path(__file__).resolve().parents[1]))).expanduser()
WORLD = ROOT / "data" / "detroit_persistent"
LOGS = ROOT / "logs"
ENGINE_LOGS = [
    LOGS / "detroit-persistent-launchd-error.log",
    LOGS / "detroit-persistent-launchd.log",
    LOGS / "detroit-manual-start.log",
]
HEARTBEAT = ROOT / "runtime" / "engine_heartbeat.json"
BOOT_STATE = ROOT / "runtime" / "boot_state"
RIGHT_SIZING_LOG = ROOT / "runtime" / "right_sizing_requests.jsonl"
HOST = "127.0.0.1"
PORT = 8767
VERSION = "1.7.4.5.1-right-sizing"
MODEL_SPECS = [
    ("social", "Social 350M", 8084),
    ("citizen", "Citizen 1.2B", 8081),
    ("strategy", "Strategy 2.6B", 8082),
    ("cyber", "Cyber 7B", 8083),
]
STAGE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d+)?\s+-\s+world\s+-\s+INFO\s+-\s+==\s+(?P<stage>.+?)\s+STAGE\s+==(?P<tail>.*)$")
AGENT_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d+)?\s+-\s+agent_(?P<agent>.+?)\s+-\s+INFO\s+-\s+(?P<msg>.*)$")
WORLD_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d+)?\s+-\s+world\s+-\s+INFO\s+-\s+(?P<msg>.*)$")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def tail_lines(path: Path, max_bytes: int = 512_000, max_lines: int = 1800) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def engine_lines() -> list[str]:
    for path in ENGINE_LOGS:
        if path.exists() and path.stat().st_size:
            return tail_lines(path)
    return []


def parse_ts(raw: str) -> float | None:
    try:
        return time.mktime(time.strptime(raw, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def engine_alive() -> bool:
    hb = read_json(HEARTBEAT, {})
    try:
        if time.time() - float(hb.get("unix", 0)) < 20:
            return True
    except Exception:
        pass
    try:
        cp = subprocess.run(["pgrep", "-f", "[r]un_detroit_persistent.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
        return cp.returncode == 0
    except Exception:
        return False


def heartbeat_age() -> float | None:
    hb = read_json(HEARTBEAT, {})
    try:
        return max(0.0, time.time() - float(hb.get("unix", 0)))
    except Exception:
        try:
            return max(0.0, time.time() - HEARTBEAT.stat().st_mtime)
        except Exception:
            return None


def active_count() -> int:
    view = WORLD / ".active_persona_view"
    try:
        if view.exists():
            return sum(1 for p in view.iterdir() if p.is_dir() or p.is_symlink())
    except Exception:
        pass
    persona = WORLD / "persona"
    try:
        return sum(1 for p in persona.iterdir() if p.is_dir() and not (p / "_background.json").exists())
    except Exception:
        return 0


def contact_slots() -> int:
    cfg = read_json(WORLD / "config.json", {})
    try:
        return max(1, int(cfg.get("world", {}).get("time", {}).get("n_contact_slot", 4)))
    except Exception:
        return 4


def current_stage(lines: list[str]) -> dict[str, Any]:
    latest: dict[str, Any] = {"name": "UNKNOWN", "tail": "", "started_at": None, "line_index": 0}
    for idx, line in enumerate(lines):
        m = STAGE_RE.match(line)
        if not m:
            continue
        latest = {
            "name": m.group("stage").strip().upper().replace("_", " "),
            "raw_name": m.group("stage").strip().upper().replace(" ", "_"),
            "tail": m.group("tail").strip(),
            "started_at": parse_ts(m.group("ts")),
            "line_index": idx,
        }
    if latest.get("started_at"):
        latest["elapsed_seconds"] = max(0, int(time.time() - float(latest["started_at"])))
    else:
        latest["elapsed_seconds"] = None
    return latest


def phase_progress(lines: list[str], stage: dict[str, Any], total: int) -> dict[str, Any]:
    part = lines[int(stage.get("line_index", 0)) + 1:]
    raw = str(stage.get("raw_name") or "").upper()
    seen: set[str] = set()
    completed: set[str] = set()
    for line in part:
        m = AGENT_RE.match(line)
        if not m:
            continue
        name = m.group("agent").strip()
        msg = m.group("msg")
        if raw and f"[{raw}]" in msg:
            seen.add(name)
        if raw == "PLAN" and "[LIVING_STANDARD]" in msg:
            completed.add(name)
        elif raw != "PLAN" and raw and f"[{raw}]" in msg:
            completed.add(name)
    if raw == "PLAN":
        done = len(completed)
        text = f"{done}/{total} citizens completed weekly planning" if total else f"{done} citizens completed weekly planning"
        pct = round((done / total) * 100) if total else 0
        return {"done": done, "seen": len(seen), "total": total, "percent": min(100, pct), "text": text}
    if raw == "CONTACT":
        slot_match = re.search(r"slot=(\d+)", str(stage.get("tail") or ""), re.I)
        slot = int(slot_match.group(1)) if slot_match else 0
        slots = contact_slots()
        pct = round(((max(0, slot - 1)) / slots) * 100) if slots else 0
        text = f"Contact slot {slot}/{slots} • {len(seen)} citizens active in this slot" if slot else f"{len(seen)} citizens active in contact phase"
        return {"done": max(0, slot - 1), "seen": len(seen), "total": slots, "percent": min(100, pct), "text": text}
    done = len(completed or seen)
    pct = round((done / total) * 100) if total else 0
    label = str(stage.get("name") or "phase").title()
    text = f"{done}/{total} citizens have reported activity in {label}" if total else f"{done} citizens active in {label}"
    return {"done": done, "seen": len(seen), "total": total, "percent": min(100, pct), "text": text}


def http_json(url: str, timeout: float = 0.8) -> Any:
    try:
        req = Request(url, headers={"User-Agent": "AgentopiaCityPulse/1.6.1.3"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def model_pool(name: str, label: str, port: int) -> dict[str, Any]:
    slots = http_json(f"http://127.0.0.1:{port}/slots")
    healthy = slots is not None
    busy = None
    total = None
    if isinstance(slots, list):
        total = len(slots)
        busy = 0
        for x in slots:
            if not isinstance(x, dict):
                continue
            if x.get("is_processing") is True:
                busy += 1
                continue
            state = str(x.get("state") or "").lower()
            if state and state not in {"idle", "available", "0"}:
                busy += 1
    if not healthy:
        healthy = http_json(f"http://127.0.0.1:{port}/health") is not None
    return {"name": name, "label": label, "port": port, "healthy": bool(healthy), "busy": busy, "slots": total}


def _run_text(cmd: list[str], timeout: float = 1.2) -> str:
    try:
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout)
        return cp.stdout.strip() if cp.returncode == 0 else ""
    except Exception:
        return ""


def system_performance() -> dict[str, Any]:
    """Best-effort host CPU and memory telemetry without third-party packages."""
    cpu_count = max(1, int(os.cpu_count() or 1))
    cpu_pct = None
    raw = _run_text(["ps", "-A", "-o", "%cpu="])
    if raw:
        try:
            total_cpu = sum(float(x.strip()) for x in raw.splitlines() if x.strip())
            cpu_pct = round(max(0.0, min(100.0, total_cpu / cpu_count)), 1)
        except Exception:
            cpu_pct = None
    if cpu_pct is None:
        try:
            cpu_pct = round(max(0.0, min(100.0, (os.getloadavg()[0] / cpu_count) * 100.0)), 1)
        except Exception:
            pass

    total = used = None
    if sys.platform == "darwin":
        try:
            total = int(_run_text(["sysctl", "-n", "hw.memsize"]) or 0)
            page_size = int(_run_text(["sysctl", "-n", "hw.pagesize"]) or 4096)
            vm = _run_text(["vm_stat"])
            pages = {}
            for line in vm.splitlines():
                m = re.match(r"([^:]+):\s+(\d+)", line)
                if m:
                    pages[m.group(1).strip().lower()] = int(m.group(2))
            free_pages = sum(pages.get(k, 0) for k in ("pages free", "pages speculative"))
            if total:
                used = max(0, total - free_pages * page_size)
        except Exception:
            total = used = None
    elif Path("/proc/meminfo").exists():
        try:
            vals = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                vals[k] = int(v.strip().split()[0]) * 1024
            total = vals.get("MemTotal")
            avail = vals.get("MemAvailable")
            if total is not None and avail is not None:
                used = max(0, total - avail)
        except Exception:
            total = used = None

    mem_pct = round((used / total) * 100.0, 1) if total and used is not None else None
    gb = 1024.0 ** 3
    return {
        "cpu_percent": cpu_pct,
        "cpu_count": cpu_count,
        "memory_total_gb": round(total / gb, 1) if total else None,
        "memory_used_gb": round(used / gb, 1) if used is not None else None,
        "memory_percent": mem_pct,
        "platform": sys.platform,
    }


def right_sizing_requests(max_bytes: int = 4_000_000, max_lines: int = 20000) -> dict[str, Any]:
    """Aggregate privacy-safe inference events emitted by src.utils."""
    rows = tail_lines(RIGHT_SIZING_LOG, max_bytes=max_bytes, max_lines=max_lines)
    now = time.time()
    tiers = {"350M": [], "1.2B": [], "2.6B": [], "specialist": [], "other": []}
    recent_60 = {k: 0 for k in tiers}
    success = 0
    parsed = 0
    latencies = []
    for line in rows:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        tier = str(obj.get("tier") or "other")
        if tier not in tiers:
            tier = "other"
        try:
            latency = max(0.0, float(obj.get("latency_ms", 0) or 0))
        except Exception:
            latency = 0.0
        try:
            ts = float(obj.get("unix", 0) or 0)
        except Exception:
            ts = 0.0
        tiers[tier].append(latency)
        latencies.append(latency)
        parsed += 1
        if obj.get("success") is True:
            success += 1
        if ts and now - ts <= 60:
            recent_60[tier] += 1

    core_total = sum(len(tiers[k]) for k in ("350M", "1.2B", "2.6B"))
    all_total = max(1, parsed)
    distribution = []
    for tier in ("350M", "1.2B", "2.6B", "specialist", "other"):
        vals = tiers[tier]
        distribution.append({
            "tier": tier,
            "requests": len(vals),
            "share_percent": round((len(vals) / all_total) * 100.0, 1) if parsed else 0.0,
            "avg_latency_ms": round(sum(vals) / len(vals), 1) if vals else None,
            "recent_60s": recent_60[tier],
        })
    return {
        "requests": parsed,
        "successful": success,
        "success_percent": round((success / parsed) * 100.0, 1) if parsed else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "core_requests": core_total,
        "distribution": distribution,
        "window_note": f"latest {parsed:,} uncached inference calls" if parsed else "waiting for uncached inference calls",
    }


def newest_world_write() -> tuple[float | None, str | None]:
    candidates: list[Path] = []
    try:
        candidates.extend((WORLD / "persona").glob("*/state.jsonl"))
    except Exception:
        pass
    for rel in [
        "public_events.jsonl",
        "social/pulses.ndjson",
        "mission_justice/events.ndjson",
        "mission_justice/state.json",
        "finance/ledger.ndjson",
        "finance/summary.json",
        "cognitive_society.json",
        "human_lifecycle.json",
    ]:
        p = WORLD / rel
        if p.exists():
            candidates.append(p)
    newest: Path | None = None
    newest_m = 0.0
    for p in candidates:
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > newest_m:
            newest_m, newest = m, p
    if newest is None:
        return None, None
    try:
        label = str(newest.relative_to(WORLD))
    except Exception:
        label = newest.name
    return max(0.0, time.time() - newest_m), label


def pulse_event(line: str) -> dict[str, str] | None:
    sm = STAGE_RE.match(line)
    if sm:
        stage = sm.group("stage").strip().replace("_", " ").title()
        tail = sm.group("tail").strip()
        return {"time": sm.group("ts")[11:19], "text": f"Simulation entered {stage}{(' • ' + tail) if tail else ''}"}
    am = AGENT_RE.match(line)
    if am:
        agent = am.group("agent").strip()
        msg = am.group("msg")
        ts = am.group("ts")[11:19]
        if "start planning" in msg:
            return {"time": ts, "text": f"{agent} started weekly planning"}
        lm = re.search(r"\[LIVING_STANDARD\].*?chose\s+([^,]+)", msg)
        if lm:
            return {"time": ts, "text": f"{agent} chose {lm.group(1).strip()} living standard"}
        if "[CONTACT]" in msg and "start" in msg.lower():
            return {"time": ts, "text": f"{agent} entered social contact"}
        if "[ACTIVITY]" in msg and "start" in msg.lower():
            return {"time": ts, "text": f"{agent} started an activity"}
        return None
    wm = WORLD_RE.match(line)
    if wm:
        msg = wm.group("msg")
        ts = wm.group("ts")[11:19]
        pm = re.search(r"Public events this week:\s*(\d+) total,\s*(\d+) new", msg)
        if pm:
            return {"time": ts, "text": f"City scheduled {pm.group(1)} public events ({pm.group(2)} new)"}
        im = re.search(r"(.+?) received weekly_income (\d+), deposit: (\d+) -> (\d+)", msg)
        if im:
            return {"time": ts, "text": f"{im.group(1)} received ${int(im.group(2)):,} weekly income"}
        lowered = msg.lower()
        if any(k in lowered for k in ("mission", "warrant", "arrest", "court", "fraud", "recovered", "faction", "transaction", "treasury")):
            clean = re.sub(r"\s+", " ", msg).strip()
            return {"time": ts, "text": clean[:150]}
    return None


def city_pulse(lines: list[str], limit: int = 14) -> list[dict[str, str]]:
    out: deque[dict[str, str]] = deque(maxlen=limit)
    last = None
    for line in lines[-900:]:
        ev = pulse_event(line)
        if not ev:
            continue
        key = ev["text"]
        if key == last:
            continue
        out.append(ev)
        last = key
    return list(out)


def boot_state() -> str:
    try:
        return BOOT_STATE.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def snapshot() -> dict[str, Any]:
    lines = engine_lines()
    total = active_count()
    stage = current_stage(lines)
    write_age, write_source = newest_world_write()
    models = [model_pool(*spec) for spec in MODEL_SPECS]
    hb_age = heartbeat_age()
    perf = system_performance()
    routing = right_sizing_requests()
    core_names = {"social", "citizen", "strategy"}
    busy = sum(int(m.get("busy") or 0) for m in models if m.get("name") in core_names)
    slots = sum(int(m.get("slots") or 0) for m in models if m.get("name") in core_names)
    performance = {
        **perf,
        **routing,
        "core_busy_slots": busy,
        "core_total_slots": slots,
        "core_slot_percent": round((busy / slots) * 100.0, 1) if slots else None,
        "local_core_models": 3,
    }
    return {
        "version": VERSION,
        "generated_unix": time.time(),
        "engine": {
            "alive": engine_alive(),
            "heartbeat_age": round(hb_age, 1) if hb_age is not None else None,
            "boot_state": boot_state(),
        },
        "phase": stage,
        "progress": phase_progress(lines, stage, total),
        "active_citizens": total,
        "models": models,
        "performance": performance,
        "world_write": {
            "age": round(write_age, 1) if write_age is not None else None,
            "source": write_source,
        },
        "pulse": city_pulse(lines),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentopiaCityPulse/1.6.1.3"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def headers_common(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")

    def send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.headers_common()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.headers_common()
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self.send_json(200, {"status": "ok", "version": VERSION, "engine_alive": engine_alive()})
        elif path == "/api/telemetry":
            self.send_json(200, snapshot())
        else:
            self.send_json(404, {"error": "not_found"})


def main() -> None:
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Agentopia City Pulse v{VERSION} listening on http://{HOST}:{PORT}", flush=True)
    srv.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
