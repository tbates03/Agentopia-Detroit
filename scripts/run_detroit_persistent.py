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

# AGENTOPIA_DETROIT_GROWTH_CALENDAR_V180
# Original Agentopia models a compressed 10-week year. Detroit's lifecycle,
# careers, education, weather, seasons and research timeline are year-based, so
# the persistent city uses a real 52-week simulation year while retaining five
# LLM-heavy activity days per week.
time_cfg["n_week"] = 52
time_cfg["n_day"] = 5
time_cfg["n_year"] = max(int(time_cfg.get("n_year", 10)), year - start + 1000, 1_000_000)

# Reward history must divide the 52-week Detroit year cleanly.
reward_cfg = world.setdefault("reward", {})
reward_cfg["period_weeks"] = 13

growth_cfg = world.setdefault("growth", {})
growth_cfg.setdefault("annual_migration_rate", 0.02)
growth_cfg.setdefault("annual_migration_min", 2)
growth_cfg.setdefault("annual_migration_max", 8)
growth_cfg.setdefault("promotions_per_year", 4)
growth_cfg.setdefault("active_ai_min", 64)
growth_cfg.setdefault("active_ai_max", 128)
growth_cfg.setdefault("global_prompt_agent_limit", 48)
growth_cfg.setdefault("encounter_prompt_agents_per_day", 48)
growth_cfg.setdefault("public_location_people_per_location", 3)
growth_cfg.setdefault("public_location_max", 120)
write(cfg_path, cfg)

# Refresh persistent background society and promote a bounded number of adults
# into durable persona directories before the active AI cohort is selected.
_growth_preflight = {}
try:
    import detroit_growth_manager as _agentopia_growth
    _growth_preflight = _agentopia_growth.prepare_for_boot()
except Exception as _growth_error:
    print(f"[growth] WARNING: preflight failed: {_growth_error}")
    _agentopia_growth = None

# Build a bounded, non-destructive active-persona view. Population may grow far
# beyond the LLM-active cohort; persistent personas retain their state while
# local compute controls how many think in the foreground on this boot.
persona_root = WORLD / "persona"
all_personas = [p for p in persona_root.iterdir() if p.is_dir()]
foreground = sorted(
    [p for p in all_personas if not (p / "_background.json").exists()],
    key=lambda p: p.name.casefold(),
)
background = sorted(
    [p for p in all_personas if (p / "_background.json").exists()],
    key=lambda p: p.name.casefold(),
)

factions = read(WORLD / "factions.json", {})
faction_names = set()
if isinstance(factions, dict):
    for f in (factions.get("factions") or {}).values():
        if isinstance(f, dict):
            faction_names.update(str(x) for x in (f.get("members") or []))

if _agentopia_growth is not None:
    active_target = _agentopia_growth.recommend_active_target(len(all_personas))
else:
    active_target = min(
        len(all_personas),
        int(os.environ.get("AGENTOPIA_ACTIVE_CITIZENS", growth_cfg.get("active_ai_min", 64))),
    )

# Mission/faction leaders are pinned, then existing foreground citizens are
# preferred, then growth-pool/background citizens fill new capacity.
by_name = {p.name: p for p in all_personas}
pinned_names = {"TGOT", "Morbeious"} | faction_names
active = []
seen = set()

def _add_persona(path):
    if path is None or path.name in seen or len(active) >= active_target:
        return
    active.append(path)
    seen.add(path.name)

for name in sorted(pinned_names, key=lambda x: (0 if x in {"TGOT", "Morbeious"} else 1, x.casefold())):
    _add_persona(by_name.get(name))
for p in foreground:
    _add_persona(p)
for p in background:
    _add_persona(p)

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
    # The runtime view is already the explicit active cohort. Background markers
    # describe canonical storage status and must not filter citizens out again.
    _include_background_personas = True

    def _persona_root(self) -> Path:
        return VIEW

    def _grow_positions(self, current_year: int, is_first_year: bool) -> None:
        # Detroit Career + Business Economy are authoritative after bootstrap.
        # Keep the original first-year merge for compatibility, but do not let
        # legacy Agentopia invent a second job market every subsequent year.
        if is_first_year:
            return super()._grow_positions(current_year, is_first_year)
        self.logger.info(
            "[DETROIT_GROWTH] legacy position growth skipped; Career Economy is authoritative"
        )

    def _run_position_application_season(self) -> None:
        self.logger.info(
            "[DETROIT_GROWTH] legacy annual position application skipped; Career Economy is authoritative"
        )

    # AGENTOPIA_YEARLY_COHORT_RECYCLE_V180
    def run(self):
        """Run exactly one simulation year, then recycle the process safely.

        A yearly process boundary lets the growth manager promote background
        residents, refresh the bounded active cohort, carry forward inactive
        profiles, and clear long-lived model/cache fragmentation without ever
        editing the checkpoint by hand.
        """
        start_year = int(self.config["time"]["start_year"])
        original_n_year = int(self.config["time"]["n_year"])
        one_year_span = max(1, int(self._resume_year) - start_year + 1)
        self.config["time"]["n_year"] = min(original_n_year, one_year_span)
        self.logger.info(
            "[DETROIT_GROWTH] yearly cohort cycle: resume_year=%d active=%d",
            int(self._resume_year),
            len(self.agents),
        )
        try:
            super().run()
        finally:
            self.config["time"]["n_year"] = original_n_year
        return "year_complete"

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
    print(f"[humanity] Human Lifecycle & Belief Engine v{_agentopia_humanity.VERSION} active")
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
print(f"[persistent] active_ai={len(active)}/{len(all_personas)} target={active_target} cyber_model={cyber_ready}")
print(f"[persistent] calendar=52weeks x 5 activity-days growth={_growth_preflight or 'preflight-unavailable'}")
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

_cycle_result = w.run()
try: merge_run_cache("detroit_persistent")
except Exception: pass

# Exit code 75 is an intentional year-boundary recycle request. The persistent
# service wrapper immediately starts the next year from the committed checkpoint.
if _cycle_result == "year_complete":
    raise SystemExit(75)
