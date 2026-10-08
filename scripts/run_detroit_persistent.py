#!/usr/bin/env python3
from __future__ import annotations
import atexit, json, os, shutil, signal, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
VIEW = WORLD / ".active_persona_view"
META = WORLD / "persistent_world.json"
VERSION = "1.7.4.5.1"


def now(): return datetime.now(timezone.utc).isoformat()
def read(path, default):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception: return default

def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def health(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=.7) as r:
            return r.status == 200
    except Exception:
        return False

if not (WORLD / "config.json").exists() or not (WORLD / "persona").exists():
    raise SystemExit(f"Persistent Detroit world is incomplete: {WORLD}")

# Ensure config always points to the canonical world and has long runway.
cfg_path = WORLD / "config.json"
cfg = read(cfg_path, {})
world = cfg.setdefault("world", {})
world["name"] = "detroit"
world["data_dir"] = "detroit_persistent"
time_cfg = world.setdefault("time", {})
start = int(time_cfg.get("start_year", 2045))
cp = read(WORLD / "checkpoint.json", {})
year = int(cp.get("year", start)) if isinstance(cp, dict) else start
time_cfg["n_year"] = max(int(time_cfg.get("n_year", 10)), year - start + 1000, 5000)
write(cfg_path, cfg)

# Build a non-destructive active-persona view. Agentopia core remains untouched.
persona_root = WORLD / "persona"
# AGENTOPIA_ULTRAPLUS_ACTIVE48_V142
all_personas = [p for p in persona_root.iterdir() if p.is_dir()]
foreground = [p for p in all_personas if not (p / "_background.json").exists()]
background = [p for p in all_personas if (p / "_background.json").exists()]
foreground.sort(key=lambda p: p.name.casefold())
background.sort(key=lambda p: p.name.casefold())
active_target = int(os.environ.get("AGENTOPIA_ACTIVE_CITIZENS", "64"))
# Never deactivate an already-active citizen. Borrow enough background founders
# into the runtime VIEW to reach the performance target. Canonical markers stay intact.
active = foreground + background[:max(0, active_target - len(foreground))]

leader_order = {"TGOT": 0, "Morbeious": 1}
active.sort(key=lambda p: (leader_order.get(p.name, 10), p.name.casefold()))
if VIEW.exists() or VIEW.is_symlink():
    if VIEW.is_dir() and not VIEW.is_symlink(): shutil.rmtree(VIEW)
    else: VIEW.unlink()
VIEW.mkdir(parents=True, exist_ok=True)
for p in active:
    try: (VIEW / p.name).symlink_to(p, target_is_directory=True)
    except FileExistsError: pass

# Faction membership drives cyber-specialist routing when the optional cyber
# server is available. Otherwise those citizens use the 2.6B strategy pool.
factions = read(WORLD / "factions.json", {})
faction_names = set()
if isinstance(factions, dict):
    for f in (factions.get("factions") or {}).values():
        if isinstance(f, dict): faction_names.update(str(x) for x in (f.get("members") or []))
cyber_ready = health(8083)
assign_path = WORLD / "model_assignment.json"
assignment = read(assign_path, {})
if not isinstance(assignment, dict): assignment = {}
for p in active:
    name = p.name
    if name in {"TGOT", "Morbeious"}:
        assignment[name] = "liquid-strategy"
    elif name in faction_names:
        assignment[name] = "cyber-specialist" if cyber_ready else "liquid-strategy"
    else:
        assignment[name] = "liquid-citizen"
write(assign_path, dict(sorted(assignment.items())))

meta = read(META, {})
if not isinstance(meta, dict): meta = {}
meta.update({
    "app_version": VERSION,
    "last_started_at": now(),
    "boot_count": int(meta.get("boot_count", 0)) + 1,
    "resume_checkpoint": cp,
    "active_ai_citizens": len(active),
    "active_persona_view": str(VIEW),
    "cyber_model_ready": cyber_ready,
})
write(META, meta)

os.chdir(ROOT)
# AGENTOPIA_REPO_BOOTSTRAP
from pathlib import Path as _AgentopiaPath
import sys as _agentopia_sys
import os as _agentopia_os

_AGENTOPIA_ROOT = _AgentopiaPath(__file__).resolve().parents[1]

if str(_AGENTOPIA_ROOT) not in _agentopia_sys.path:
    _agentopia_sys.path.insert(0, str(_AGENTOPIA_ROOT))

_agentopia_os.chdir(_AGENTOPIA_ROOT)

from src.config import load_config
load_config(cfg_path)
from src.utils import set_run_cache_dir, flush_all_caches, merge_run_cache
set_run_cache_dir("detroit_persistent")
from src.world.world import World

class PersistentDetroitWorld(World):
    def _persona_root(self) -> Path:
        return VIEW

# AGENTOPIA_COGNITIVE_RUNTIME_V130
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_cognitive_society as _agentopia_cognition
    _agentopia_cognition.update()
    _agentopia_cognition.apply_assignment()
    _agentopia_cognition.apply_runtime_patches()
    print("[cognition] Cognitive Society Engine v1.3.0 active")
except Exception as _cognition_error:
    print(f"[cognition] WARNING: sidecar initialization failed: {_cognition_error}")

# AGENTOPIA_HUMANITY_RUNTIME_V140
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_human_lifecycle as _agentopia_humanity
    _agentopia_humanity.update()
    _agentopia_humanity.apply_runtime_patch()
    print("[humanity] Human Lifecycle & Belief Engine v1.4.0 active")
except Exception as _humanity_error:
    print(f"[humanity] WARNING: sidecar initialization failed: {_humanity_error}")

# AGENTOPIA_SOCIAL_RUNTIME_V143
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_social_faction as _agentopia_social
    _agentopia_social.apply_runtime_patches()
    print("[social] Social Quality + Telemetry v1.4.5 active")
except Exception as _social_error:
    print(f"[social] WARNING: sidecar initialization failed: {_social_error}")

# AGENTOPIA_LIQUID_NATIVE_RUNTIME_V144
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_liquid_native as _agentopia_liquid
    _agentopia_liquid.apply_runtime_patches()
    print("[liquid] Liquid Native Engine v1.4.4 active")
except Exception as _liquid_error:
    print(f"[liquid] WARNING: sidecar initialization failed: {_liquid_error}")

# AGENTOPIA_MISSION_RUNTIME_V160_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_mission_justice as _agentopia_missions
    _agentopia_missions.apply_runtime_patches()
    print("[mission] Mission, Crime & Justice Engine v1.6.0 active")
except Exception as _mission_error:
    print(f"[mission] WARNING: sidecar initialization failed: {_mission_error}")
# AGENTOPIA_MISSION_RUNTIME_V160_END

# AGENTOPIA_FINANCE_RUNTIME_V161_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_financial_system as _agentopia_finance
    _agentopia_finance.apply_runtime_patches()
    print("[finance] Financial Network v1.6.1 active")
except Exception as _finance_error:
    print(f"[finance] WARNING: sidecar initialization failed: {_finance_error}")
# AGENTOPIA_FINANCE_RUNTIME_V161_END

# AGENTOPIA_CAREER_RUNTIME_V1614_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_career_economy as _agentopia_careers
    _agentopia_careers.apply_runtime_patches()
    print("[career] Career Economy v1.6.1.4 active - 200 professions")
except Exception as _career_error:
    print(f"[career] WARNING: sidecar initialization failed: {_career_error}")
# AGENTOPIA_CAREER_RUNTIME_V1614_END


# AGENTOPIA_HUMAN_ECONOMY_RUNTIME_V170_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_human_economy as _agentopia_human_economy
    _agentopia_human_economy.apply_runtime_patches()
    print("[economy] Human Economy v1.7.0 active - housing, cost of living, consumption and taxes")
except Exception as _economy_error:
    print(f"[economy] WARNING: sidecar initialization failed: {_economy_error}")
# AGENTOPIA_HUMAN_ECONOMY_RUNTIME_V170_END

# AGENTOPIA_BUSINESS_ECONOMY_RUNTIME_V171_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_business_economy as _agentopia_business
    _agentopia_business.apply_runtime_patches()
    print("[business] Business Economy v1.7.1 active - firms, revenue, payroll, debt, hiring and bankruptcy")
except Exception as _business_error:
    print(f"[business] WARNING: sidecar initialization failed: {_business_error}")
# AGENTOPIA_BUSINESS_ECONOMY_RUNTIME_V171_END

# AGENTOPIA_EDUCATION_SKILLS_RUNTIME_V172_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_education_skills as _agentopia_education
    _agentopia_education.apply_runtime_patches()
    print("[education] Education & Skills Economy v1.7.2 active - schools, trades, degrees, skills, tuition and student debt")
except Exception as _education_error:
    print(f"[education] WARNING: sidecar initialization failed: {_education_error}")
# AGENTOPIA_EDUCATION_SKILLS_RUNTIME_V172_END

# AGENTOPIA_HEALTHCARE_RUNTIME_V173_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_healthcare as _agentopia_healthcare
    _agentopia_healthcare.apply_runtime_patches()
    print("[healthcare] Health & Healthcare Economy v1.7.3 active - health, care, insurance claims, providers and medical payment plans")
except Exception as _healthcare_error:
    print(f"[healthcare] WARNING: sidecar initialization failed: {_healthcare_error}")
# AGENTOPIA_HEALTHCARE_RUNTIME_V173_END

# AGENTOPIA_WORLD_CONTEXT_RUNTIME_V100_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_world_context as _agentopia_world_context
    _agentopia_world_context.apply_runtime_patches()
    print("[world-context] Weather, Seasons & Cultural Calendar Engine v1.0.0 active")
except Exception as _world_context_error:
    print(f"[world-context] WARNING: sidecar initialization failed: {_world_context_error}")
# AGENTOPIA_WORLD_CONTEXT_RUNTIME_V100_END

# AGENTOPIA_MOBILITY_RUNTIME_V174_START
try:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import detroit_mobility_time as _agentopia_mobility
    _agentopia_mobility.apply_runtime_patches()
    print("[mobility] Mobility & Time v1.7.4 active - 24-hour routines, travel time, vehicles, transit, congestion and Detroit corridors")
except Exception as _mobility_error:
    print(f"[mobility] WARNING: sidecar initialization failed: {_mobility_error}")
# AGENTOPIA_MOBILITY_RUNTIME_V174_END

w = PersistentDetroitWorld(parallel=True, no_context_engineering=False, no_history=False)
atexit.register(flush_all_caches)
_flushing = False

def stop(signum, frame):
    global _flushing
    if _flushing: raise SystemExit(130)
    _flushing = True
    try: flush_all_caches()
    finally: raise SystemExit(0)

signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
print(f"[persistent] Agentopia Detroit v{VERSION}")
print("[persistent] world=data/detroit_persistent")
print(f"[persistent] active_ai={len(active)} cyber_model={cyber_ready}")
print("[persistent] resume=checkpoint")
# AGENTOPIA_ENGINE_HEARTBEAT_V1612_START
import threading as _agentopia_hb_threading
import time as _agentopia_hb_time
_ENGINE_HEARTBEAT = ROOT / "runtime" / "engine_heartbeat.json"
def _agentopia_engine_heartbeat():
    while True:
        try:
            _ENGINE_HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
            _tmp = _ENGINE_HEARTBEAT.with_suffix('.tmp')
            _tmp.write_text(json.dumps({
                "pid": os.getpid(),
                "unix": _agentopia_hb_time.time(),
                "version": VERSION,
                "world": "detroit_persistent",
            }, indent=2), encoding='utf-8')
            _tmp.replace(_ENGINE_HEARTBEAT)
        except Exception:
            pass
        _agentopia_hb_time.sleep(5)
_agentopia_hb_threading.Thread(target=_agentopia_engine_heartbeat, name='agentopia-engine-heartbeat', daemon=True).start()
# AGENTOPIA_ENGINE_HEARTBEAT_V1612_END

w.run()
try: merge_run_cache("detroit_persistent")
except Exception: pass
