from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.world.clock import Clock, Stage, TimeState
from src.agents.role_agent import RoleAgent
from src.world.scheduling import MessageCenter, Schedule, PublicEvent
from src.world.cleanup import clean_append_only_jsonl_before
from src.world.god import init_god_module
from src.utils import get_logger, pool_size, set_log_run_id
from src.config import get_world_config, get_config
from src.world.activity import JointActivity, SoloActivity


class World:
    """Minimal world runner following the pseudo/world.py stages."""

    def __init__(
        self,
        *,
        no_context_engineering: bool = False,
        parallel: bool = False,
        config_path: str | None = None,
        no_history: bool = False,
        max_agents: int | None = None,
        resume_from: Optional[Tuple[int, int]] = None,
    ) -> None:
        self.config = get_world_config()
        self.clock = Clock(start_year=self.config["time"]["start_year"], start_week=0)

        # data_dir: file path (includes run_id); name: logical identifier (used for prompts)
        self.data_dir = self.config["data_dir"]

        # Set up the run-specific log directory: logs/{run_id}/
        run_id = Path(self.data_dir).name
        set_log_run_id(run_id)

        # world logger prints to console; log file: logs/{run_id}/world.log
        self.logger = get_logger("world", quiet=False)

        # Initialize God module for SFT data collection
        init_god_module(clock=self.clock, data_dir=self.data_dir)

        # Create cache logger with run_id for cache hit/miss logs
        # File: logs/world_{worldname}_{runid}.log (e.g., logs/world_schooldays_01151703.log)
        # This logger only writes to file, not console
        cache_logger_name = f"world_{Path(self.data_dir).name}"
        get_logger(cache_logger_name, quiet=True)

        # Determine resume point (for cleanup and run loop)
        self._resume_year, self._resume_week = self._resolve_resume_point(resume_from)
        start_time = TimeState(self._resume_year, self._resume_week, Stage.BEGIN)
        self.logger.info(
            f"Resume point: Y{self._resume_year}-W{self._resume_week:02d} "
            f"(cleanup from {start_time})"
        )
        clean_append_only_jsonl_before(world_name=self.data_dir, start_time=start_time)

        self.no_context_engineering = no_context_engineering
        self.parallel = parallel
        # Concurrency cap from root config; fail fast if missing.
        root_cfg = get_config()

        # role_model: str | list[str] from config
        role_model_cfg = root_cfg["role_model"]
        if isinstance(role_model_cfg, str):
            self._role_models = [role_model_cfg]
        else:
            self._role_models = list(role_model_cfg)
        if not self._role_models:
            raise ValueError("role_model config must not be empty")
        self.max_concurrency = int(root_cfg["max_concurrency"])
        self.no_history = no_history
        self.max_agents = max_agents  # None means no limit
        # Message center: single instance shared by world and all agents
        self.msg_center = MessageCenter(world_name=self.data_dir, clock=self.clock)

        # Bootstrap agents from existing dataset directories to avoid inventing personas here.
        # Initialize agents from data directory with a configurable cap
        self.agents: List[RoleAgent] = self._init_agents_from_data(
            max_agents=self.max_agents
        )
        # Cache name -> agent mapping (agents don't change after init)
        self._name2agent: Dict[str, RoleAgent] = {a.name: a for a in self.agents}

        # Agentopia faction/recruitment layer.
        from src.world.factions import FactionEngine

        self.faction_engine = FactionEngine(self)
        self.faction_engine.bootstrap()

    # Initialization ---------------------------------------------------------
    def _persona_root(self) -> Path:
        return Path("data") / self.data_dir / "persona"

    def _bounded_agents_for_context(
        self,
        agents: List[RoleAgent],
        *,
        purpose: str,
        limit: int | None = None,
    ) -> List[RoleAgent]:
        """Return a deterministic rotating slice for global God-model prompts.

        The simulated population may grow without forcing every citizen profile
        into every global prompt. TGOT/Morbeious remain visible when present;
        the remaining slots rotate by simulated week and purpose.
        """
        growth = self.config.get("growth", {}) if isinstance(self.config, dict) else {}
        if not isinstance(growth, dict):
            growth = {}
        if limit is None:
            raw = os.environ.get(
                "AGENTOPIA_GLOBAL_CONTEXT_AGENT_LIMIT",
                str(growth.get("global_prompt_agent_limit", 48)),
            )
            try:
                limit = int(raw)
            except Exception:
                limit = 48
        limit = max(2, int(limit))
        if len(agents) <= limit:
            return list(agents)

        by_name = {a.name: a for a in agents}
        selected: List[RoleAgent] = []
        for name in ("TGOT", "Morbeious"):
            if name in by_name and len(selected) < limit:
                selected.append(by_name[name])

        t = self.clock.get_time()
        selected_names = {a.name for a in selected}
        rest = [a for a in agents if a.name not in selected_names]
        rest.sort(
            key=lambda a: hashlib.sha256(
                f"{purpose}|Y{t.year}|W{t.week}|{a.name}".encode("utf-8")
            ).hexdigest()
        )
        selected.extend(rest[: max(0, limit - len(selected))])
        return selected

    def _init_agents_from_data(
        self, *, max_agents: int | None = None
    ) -> List[RoleAgent]:
        root = self._persona_root()
        if not root.exists():
            raise FileNotFoundError(f"persona root not found: {root}")
        # Every persona should have a profile; for simplicity we no longer filter here. If one is missing, an error will be raised later at read time to surface the problem early.
        include_background = bool(
            getattr(self, "_include_background_personas", False)
        )
        all_dirs = [
            p
            for p in sorted(root.iterdir())
            if p.is_dir()
            and (include_background or not (p / "_background.json").exists())
        ]
        names = (
            [p.name for p in all_dirs[:max_agents]]
            if max_agents
            else [p.name for p in all_dirs]
        )

        # Ensure locations file and private homes exist for current run world
        from src.world.locations import get_location_store

        self.location_store = get_location_store(self.data_dir)

        # Assign role_model to each agent (uniform distribution, persisted)
        model_assignment = self._load_or_assign_models(names)

        # Create agents first (needed for agents_summary in location generation)
        agents = [
            RoleAgent(
                n,
                clock=self.clock,
                msg_center=self.msg_center,
                model=model_assignment[n],
                world_name=self.data_dir,
                no_context_engineering=self.no_context_engineering,
                no_history=self.no_history,
            )
            for n in names
        ]

        # Build a bounded representative summary for map generation. Private
        # homes are still created for every active persona via persona_names.
        location_context_agents = self._bounded_agents_for_context(
            agents, purpose="location-generation"
        )
        agents_summary = "\n\n".join(
            f"## {a.name}\n{a.dm.get_brief_intro()}" for a in location_context_agents
        )
        if len(location_context_agents) < len(agents):
            agents_summary = (
                f"## Population context\n"
                f"Active citizens: {len(agents)}. Representative profiles shown: "
                f"{len(location_context_agents)}.\n\n" + agents_summary
            )
        self.location_store.ensure(persona_names=names, agents_summary=agents_summary)

        # Ensure positions exist (generate via God Model if needed)
        from src.world.position_application import get_position_store
        from src.agents.prompts import get_world_setting

        self.position_store = get_position_store(self.data_dir)
        world_setting = get_world_setting(self.data_dir)
        self.position_store.ensure(agents=agents, world_setting=world_setting)

        # Store initial position count for yearly growth calculation
        self._initial_position_count = self.position_store.count()

        # Ensure initial state exists (writes W00-begin entry).
        # Only on fresh start — on resume, state.jsonl already has data.
        # Writing at W00 during resume would append a time-misordered entry
        # after existing W01+ data, corrupting backward reads.
        is_fresh_start = (
            self._resume_year == self.config["time"]["start_year"]
            and self._resume_week <= 1
        )
        if is_fresh_start:
            for agent in agents:
                agent.dm.read_state()

        return agents

    # Model Assignment ---------------------------------------------------------
    def _model_assignment_path(self) -> Path:
        return Path("data") / self.data_dir / "model_assignment.json"

    def _load_or_assign_models(self, names: List[str]) -> Dict[str, str]:
        """Load or create model assignment for each agent.

        If model_assignment.json exists, load it (resume scenario).
        Otherwise, uniformly distribute role_models across agents and persist.
        """
        path = self._model_assignment_path()
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                assignment = json.load(f)
            self.logger.info(f"Loaded model assignment from {path}")
            # Validate all names are present
            missing = [n for n in names if n not in assignment]
            if missing:
                raise ValueError(f"model_assignment.json missing agents: {missing}")
            # Warn if config models differ from persisted assignment
            assigned_models = sorted(set(assignment.values()))
            config_models = sorted(self._role_models)
            if assigned_models != config_models:
                self.logger.warning(
                    f"Model assignment locked from previous run: {assigned_models}. "
                    f"Current config role_model={config_models} is ignored."
                )
            return assignment

        # New run: assign models uniformly with deterministic seed
        rng = random.Random(self.data_dir)
        models = self._role_models
        # Shuffle to avoid alphabetical bias (e.g., first N agents all get model-a)
        shuffled_names = list(names)
        rng.shuffle(shuffled_names)
        assignment = {
            name: models[i % len(models)] for i, name in enumerate(shuffled_names)
        }

        # Persist
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            # Sort by name for readability
            json.dump(dict(sorted(assignment.items())), f, indent=2, ensure_ascii=False)
        self.logger.info(
            f"Assigned {len(names)} agents to {len(models)} model(s): "
            + ", ".join(
                f"{m}={sum(1 for v in assignment.values() if v == m)}" for m in models
            )
        )
        return assignment

    # Checkpoint & Resume -----------------------------------------------------
    def _checkpoint_path(self) -> Path:
        return Path("data") / self.data_dir / "checkpoint.json"

    def _read_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Read checkpoint.json. Returns None if not found or corrupted."""
        p = self._checkpoint_path()
        if not p.exists():
            return None
        try:
            with p.open("r", encoding="utf-8") as f:
                cp = json.load(f)
            # Validate required fields
            _ = cp["year"], cp["week"]
            return cp
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self.logger.warning(f"Corrupted checkpoint.json, ignoring: {e}")
            return None

    def _write_checkpoint(self, year: int, week: int) -> None:
        """Write checkpoint.json atomically (tmp + rename).

        Progression:
        - After year-start: {"year": Y, "week": 0}
        - After week W: {"year": Y, "week": W}
        - After year-end: {"year": Y+1, "week": 0} (advance to next year)
        """
        data = {"year": year, "week": week}
        p = self._checkpoint_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.rename(p)

    def _resolve_resume_point(
        self, resume_from: Optional[Tuple[int, int]]
    ) -> Tuple[int, int]:
        """Determine (resume_year, resume_week) for the run loop.

        Priority:
        1. --resume-from override
        2. checkpoint.json auto-detection
        3. Fresh start from config start_year, week 1

        Checkpoint semantics: {"year": Y, "week": W}
        - week == 0: year-start done, no week completed → resume from (Y, 1)
        - week < n_week: week W done → resume from (Y, W+1)
        - week == n_week: all weeks done, year-end may not have completed
          → resume from (Y, n_week) to re-run last week + year-end
          (cheap: cache hit on the week, ensures year-end completes)
        """
        start_year = self.config["time"]["start_year"]

        if resume_from is not None:
            return resume_from

        cp = self._read_checkpoint()
        if cp is not None:
            n_week = self.config["time"]["n_week"]
            year = cp["year"]
            week = cp["week"]
            if week == 0:
                return (year, 1)
            elif week < n_week:
                return (year, week + 1)
            else:
                # week == n_week: year-end may not have completed
                return (year, week)

        return (start_year, 1)

    # Utilities --------------------------------------------------------------
    def by_name(self) -> Dict[str, RoleAgent]:
        """Return cached mapping from character name to agent."""
        return self._name2agent

    def _collect_existing_schedules(self) -> Dict[str, Dict[str, Schedule]]:
        """Collect existing schedules for conflict detection.

        Returns schedules created before current time that are scheduled for
        future (including current week). Used to detect conflicts when confirming
        new joint activities.

        Returns:
            Dict mapping person -> activity_time (str) -> Schedule
        """
        t = self.clock.get_time()
        result: Dict[str, Dict[str, Schedule]] = {}

        for agent in self.agents:
            # Reuse get_future_schedules which handles the scheduling window
            schedules = agent.dm.get_future_schedules()
            for schd in schedules:
                # Only include schedules created before current time
                # (schedules created this week are handled by confirm_schedule itself)
                if schd.time is None or schd.time >= t:
                    continue
                act_time = str(schd.activity_time)
                if agent.name not in result:
                    result[agent.name] = {}
                result[agent.name][act_time] = schd

        return result

    def build_all_agents_summary(self) -> str:
        """Build bounded, rotating citizen context for global God-model tasks.

        Full population membership remains available to validation/routing code;
        this method prevents prompt size from growing linearly without bound.
        """
        selected = self._bounded_agents_for_context(
            self.agents, purpose="global-agent-summary"
        )
        lines = [
            "## Agentopia population context",
            f"- Active AI citizens: {len(self.agents)}",
            f"- Representative citizen profiles in this prompt: {len(selected)}",
            "- Omitted citizens still exist and retain persistent state.",
        ]
        for agent in selected:
            lines.append(f"### {agent.name}\n{agent.dm.get_brief_intro()}")
        return "\n\n".join(lines)

    # Public Events Persistence -----------------------------------------------
    def _public_events_path(self) -> Path:
        """Return path to public_events.jsonl."""
        return Path("data") / self.data_dir / "public_events.jsonl"

    def _save_public_events(self, events: List[PublicEvent]) -> None:
        """Append public events to file (with time field for cleanup support)."""
        path = self._public_events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        time_str = str(self.clock.get_time())
        with open(path, "a", encoding="utf-8") as f:
            for evt in events:
                d = {"time": time_str, **evt.to_dict()}
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    def _load_public_events(self) -> Dict[str, PublicEvent]:
        """Load public events from file, filtering out expired ones.

        File is append-only (oldest first), so we read backwards.
        Once we hit an event older than max_repeat_weeks, we can stop.

        Returns:
            Dict of event_id -> PublicEvent for all non-expired events.
        """
        import json

        path = self._public_events_path()
        if not path.exists():
            return {}

        t = self.clock.get_time()
        n_weeks_per_year = self.config["time"]["n_week"]
        current_absolute_week = t.year * n_weeks_per_year + t.week
        max_repeat_weeks = self.config["public_activity"]["max_repeat_weeks"]

        # Read all lines, then iterate backwards
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        events: Dict[str, PublicEvent] = {}
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            evt = PublicEvent.from_dict(d)

            # Early exit: if event is older than max_repeat_weeks, all previous are older
            start_absolute_week = evt.start_year * n_weeks_per_year + evt.start_week
            if current_absolute_week - start_absolute_week >= max_repeat_weeks:
                break

            # Check if expired based on actual repeat_weeks
            end_absolute_week = start_absolute_week + evt.repeat_weeks
            if current_absolute_week < end_absolute_week:
                events[evt.event_id] = evt
        return events

    def _apply_fulfillment_decay(self) -> None:
        """Apply proportional fulfillment decay: value * (1 - ratio) per dimension."""
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="fulfillment")
        decay_ratio = self.config["fulfillment_decay_min_ratio"]

        for agent in self.agents:
            fulfillment = agent.dm.get_fulfillment()
            decays = {
                key: int(value * decay_ratio[key]) for key, value in fulfillment.items()
            }

            if verify_logger:
                for key in decays:
                    new_val = max(0, fulfillment[key] - decays[key])
                    verify_logger.info(
                        f"[VERIFY-FULFILLMENT] {agent.name}.{key}: "
                        f"{fulfillment[key]} → {new_val} (-{decays[key]})"
                    )
            agent.dm.apply_fulfillment_decay(decays)

    def _settle_weekly_income(self) -> None:
        """Distribute weekly_income to all agents at the start of each week.

        REQ-10: Income has two sources.
        total_income = position_income + extra_income
        """
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="economy")

        if verify_logger:
            verify_logger.info(
                "[VERIFY-ECONOMY] Distributing weekly_income to all agents"
            )

        for agent in self.agents:
            profile = agent.dm.read_profile()
            position = profile["position"]
            position_income = position["weekly_income"]
            extra_income = profile["extra_income"]
            total_income = position_income + extra_income

            if total_income > 0:
                current_deposit = agent.dm.get_deposit()
                new_deposit = current_deposit + total_income
                agent.dm.update_deposit(new_deposit)
                self.logger.info(
                    f"{agent.name} received weekly_income {total_income}, deposit: {current_deposit} -> {new_deposit}"
                )
                if verify_logger:
                    verify_logger.info(
                        f"[VERIFY-ECONOMY] {agent.name}: total_income={total_income} "
                        f"(position={position_income}, extra={extra_income}), "
                        f"deposit {current_deposit} → {new_deposit}"
                    )
            elif verify_logger:
                verify_logger.warning(f"[VERIFY-ECONOMY] {agent.name} has zero income")

    def _before_week_start(self) -> None:
        """Execute all operations that should happen before each week starts."""
        self._apply_fulfillment_decay()
        self._settle_weekly_income()

    def _run_position_application_season(self) -> None:
        """Run position application season at year end.

        Calls run_position_application_season() from position_application module to handle
        the 1.5-round position application process.
        """
        from src.world.position_application import run_position_application_season
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="position_application")
        t = self.clock.get_time()

        # position_store is initialized in World.__init__, use it directly
        positions = self.position_store.get_all()

        self.logger.info(
            f"== POSITION APPLICATION SEASON == year={t.year} positions={len(positions)}"
        )

        # Run position application
        results = run_position_application_season(self, self.clock, parallel=self.parallel)

        # Log summary (single pass)
        accepted = sum(1 for r in results.values() if r.get("accepted"))
        unemployed = len(results) - accepted

        self.logger.info(
            f"[POSITION_APPLICATION] Complete: {accepted} accepted, {unemployed} unemployed"
        )

    def _merge_profile_positions(self) -> None:
        """Merge positions from agent profiles into PositionStore.

        Agents' initial positions (from profile templates) may not be in
        positions.json if god_design_positions() missed them. This method
        scans all agent profiles, identifies missing positions, and adds
        them with created_year=-1 (pre-simulation).
        """
        from src.world.position_application import Position

        # Scan profiles: group agents by their position name
        pos_agents: Dict[str, List[str]] = {}  # pos_name -> [agent_names]
        pos_data: Dict[str, Dict] = {}  # pos_name -> profile position data

        for agent in self.agents:
            profile = agent.dm.read_profile()
            pos = profile["position"]
            name = f"{pos['organization']}/{pos['role']}"
            pos_agents.setdefault(name, []).append(agent.name)
            if name not in pos_data:
                pos_data[name] = pos

        # Add missing positions with created_year=-1
        added = 0
        for pos_name in sorted(pos_agents.keys()):
            if self.position_store.get(pos_name) is not None:
                continue
            data = pos_data[pos_name]
            agents_holding = pos_agents[pos_name]
            org, role = Position.parse_name(pos_name)
            new_pos = Position(
                organization=org,
                role=role,
                type=data["type"],
                description=data.get("description", ""),
                weekly_income=data["weekly_income"],
                weekly_delta_skills=data["weekly_delta_skills"],
                capacity=len(agents_holding),
                occupied_by=sorted(agents_holding),
                created_year=-1,
            )
            self.position_store.add(new_pos)
            added += 1
            self.logger.info(
                f"[POSITIONS] Merged from profile: {pos_name} "
                f"(capacity={len(agents_holding)}, created_year=-1)"
            )

        if added:
            self.logger.info(
                f"[POSITIONS] Merged {added} positions from agent profiles"
            )

    def _grow_positions(self, current_year: int, is_first_year: bool) -> None:
        """Grow positions at the start of each year.

        - First year: Set created_year for all initial positions
        - Subsequent years: Generate new challenging positions

        Args:
            current_year: The current simulation year
            is_first_year: Whether this is the first year of simulation
        """
        from src.world.god import god_grow_positions
        from src.world.position_application import Position
        from src.agents.prompts import get_world_setting
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="position_application")

        if is_first_year:
            # First year: set created_year for all existing positions
            for pos in self.position_store.get_all():
                if pos.created_year is None:
                    pos.created_year = current_year

            # Merge initial positions from agent profiles that aren't in the store.
            # These are positions agents start with but god_design_positions() missed.
            self._merge_profile_positions()

            self.position_store.save()
            self.logger.info(
                f"[POSITIONS] Year {current_year}: initialized {self.position_store.count()} positions"
            )
            return

        # Subsequent years: generate new challenging positions
        # Remove any positions already created for this year (idempotent on resume)
        removed = self.position_store.remove_by_created_year(current_year)
        if removed:
            self.position_store.save()
            self.logger.info(
                f"[POSITIONS] Year {current_year}: removed {removed} stale positions (resume)"
            )

        # Formula: max(2, N/10) where N = initial position count (stable, not compounding)
        target_count = max(2, self._initial_position_count // 10)

        world_setting = get_world_setting(self.data_dir)
        existing_positions = self.position_store.get_all()

        self.logger.info(
            f"[POSITIONS] Year {current_year}: requesting {target_count} new challenging positions"
        )

        new_positions_data = god_grow_positions(
            agents=self.agents,
            world_setting=world_setting,
            existing_positions=existing_positions,
            count=target_count,
            created_year=current_year,
        )

        if new_positions_data:
            new_positions = [Position.from_dict(d) for d in new_positions_data]
            self.position_store.add_positions(new_positions)
            self.position_store.save()

            if verify_logger:
                for pos in new_positions:
                    verify_logger.info(
                        f"[POSITIONS] Added: {pos.name} (income={pos.weekly_income}, "
                        f"min_skills={pos.min_skills}, capacity={pos.capacity})"
                    )

        self.logger.info(
            f"[POSITIONS] Year {current_year}: added {len(new_positions_data) if new_positions_data else 0}, "
            f"total now {self.position_store.count()}"
        )

    # Execution --------------------------------------------------------------
    def run(self) -> None:
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="world")

        start_year = self.config["time"]["start_year"]
        total_years = self.config["time"]["n_year"]
        n_week = self.config["time"]["n_week"]
        resume_year = self._resume_year
        resume_week = self._resume_week

        for y in range(total_years):
            current_year = start_year + y

            if current_year < resume_year:
                continue

            self.clock.set_year(current_year)

            # Year-start: run _grow_positions unless resuming mid-year
            # resume_week > 1 means year-start already completed for resume_year
            need_year_start = (current_year > resume_year) or (resume_week <= 1)
            if need_year_start:
                self._grow_positions(
                    current_year, is_first_year=(current_year == start_year)
                )
                self._write_checkpoint(current_year, 0)

            for week in range(1, n_week + 1):
                if current_year == resume_year and week < resume_week:
                    continue

                self.clock.set_week(week)
                self.step()
                self._write_checkpoint(current_year, week)

            # Year-end
            self._update_yearly_profiles()
            self._run_position_application_season()
            self._calculate_rewards()
            # Advance checkpoint to next year (year-end complete)
            self._write_checkpoint(current_year + 1, 0)

        if verify_logger:
            verify_logger.info(
                "[VERIFY-COMPLETE] World simulation completed successfully"
            )

    def step(self) -> None:
        from src.world.simulation_speed import apply_speed_profile
        self.speed_state = apply_speed_profile(self)
        self.logger.info(f"== SPEED == {self.speed_state['label']} | concurrency={self.speed_state['effective_concurrency']} | timeline={self.speed_state['timeline_multiplier']}x")

        # Stage 0: before week start (fulfillment decay + weekly income)
        self._before_week_start()
        for agent in self.agents:
            agent.clear_on_week_start()

        # Stage 1: plan
        self.clock.set_stage(Stage.PLAN)
        t = self.clock.get_time()
        self.logger.info(f"== PLAN STAGE == year={t.year} week={t.week}")
        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                list(ex.map(lambda a: a.plan(), self.agents))
        else:
            for agent in self.agents:
                agent.plan()

        # Stage 2: before_contact (God Model generates events → Agents respond)
        self.clock.set_stage(Stage.BEFORE_CONTACT)
        t = self.clock.get_time()
        self.logger.info(f"== BEFORE_CONTACT STAGE == year={t.year} week={t.week}")

        # God Model: generate public events for this week
        this_week_events = self._generate_public_events()

        # Agents: sign up for public events (parallel)
        if this_week_events:
            if self.parallel:
                with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                    list(
                        ex.map(
                            lambda a: a.signup_public_events(this_week_events),
                            self.agents,
                        )
                    )
            else:
                for a in self.agents:
                    a.signup_public_events(this_week_events)
        else:
            self.logger.info("No public events available this week")

        # Stage 3: contact
        self.clock.set_stage(Stage.CONTACT)
        # start of contact phase: clear per-week msg queue
        self.msg_center.clear()
        for slot in range(1, self.config["time"]["n_contact_slot"] + 1):
            self.clock.set_slot(slot)
            t = self.clock.get_time()
            self.logger.info(
                f"== CONTACT STAGE == year={t.year} week={t.week} slot={t.slot}"
            )
            if self.parallel:
                with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                    list(ex.map(lambda a: a.contact(), self.agents))
            else:
                for agent in self.agents:
                    agent.contact()

        # Stage 4: after_contact
        self.clock.set_stage(Stage.AFTER_CONTACT)
        self.logger.info(f"== AFTER CONTACT STAGE == year={t.year} week={t.week}")

        # Collect existing schedules for conflict detection
        # (schedules created in previous weeks for future days)
        existing_schedules = self._collect_existing_schedules()

        # Confirm joint schedules from contact messages
        self.msg_center.confirm_schedule(existing_schedules=existing_schedules)

        # Agents: finalize contact (writes joint schedules to agent.dm)
        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                list(ex.map(lambda a: a.finalize_contact(), self.agents))
        else:
            for agent in self.agents:
                agent.finalize_contact()

        # God Model: generate encounter events for idle agents
        # (after finalize_contact so all schedules are in agent.dm)
        self._generate_encounter_events()

        # Stage 5: activity
        self.clock.set_stage(Stage.ACTIVITY)
        for day in range(1, self.config["time"]["n_day"] + 1):
            self.clock.set_day(day)
            t = self.clock.get_time()

            # Build today's activities (all types)
            public_acts, joint_acts, encounter_acts, solo_acts = (
                self._build_today_activities_all_types()
            )

            self.logger.info(
                f"== ACTIVITY STAGE == year={t.year} week={t.week} day={t.day} | "
                f"joint={len(joint_acts)} encounter={len(encounter_acts)} "
                f"public={len(public_acts)} solo={len(solo_acts)}"
            )

            # Execute all activity types in parallel with Semaphore-based concurrency control
            #
            # Design:
            # - Semaphore(max_concurrency) controls total concurrent tasks
            # - Joint/Solo: 1 slot each (one concurrent task)
            # - Public: N slots where N = min(participants, internal_parallelism)
            #
            # Submission order (priority):
            # 1. Joint (bottleneck, slow, gets slots first)
            # 2. Solo (fast, fills remaining slots)
            # 3. Public (sorted by size, small first to release slots quickly)
            if self.parallel:
                from src.config import get_config
                from threading import Lock, Semaphore

                cfg = get_config()
                # AGENTOPIA_ACTIVITY_EFFECTIVE_CONCURRENCY_V1745
                configured_max = int(cfg["max_concurrency"])
                speed_state = getattr(self, "speed_state", {}) or {}
                max_concurrency = int(speed_state.get("effective_concurrency", configured_max))
                max_concurrency = max(1, min(max_concurrency, configured_max))

                n_joint = len(joint_acts) + len(encounter_acts)
                n_solo = len(solo_acts)
                n_public = len(public_acts)

                # Public internal parallelism from config (must be > 0)
                public_internal_parallelism = int(
                    self.config["public_activity"]["internal_parallelism"]
                )
                if public_internal_parallelism <= 0:
                    self.logger.error(
                        f"internal_parallelism must be > 0, got {public_internal_parallelism}, forcing to 5"
                    )
                    public_internal_parallelism = 5

                self.logger.debug(
                    f"Activity parallel: joint={n_joint}, solo={n_solo}, "
                    f"public={n_public}, public_internal={public_internal_parallelism}, "
                    f"pool={max_concurrency}"
                )

                # AGENTOPIA_ACTIVITY_SLOT_DEADLOCK_FIX_V1745
                # Semaphore controls total concurrent tasks.
                #
                # Slot reservations must be atomic. Acquiring N permits one-by-one
                # without a reservation lock can deadlock when a PublicActivity
                # asks for more permits than remain available (or when multiple
                # multi-slot activities partially acquire the pool).
                capacity = Semaphore(max_concurrency)
                reservation_lock = Lock()

                def run_with_slots(fn, slots: int, *args, **kwargs):
                    """Run function while holding a safe, bounded slot reservation."""
                    requested_slots = max(1, int(slots))
                    held_slots = min(requested_slots, max_concurrency)
                    if held_slots != requested_slots:
                        self.logger.warning(
                            "[ACTIVITY_SLOT_CLAMP] requested=%d capacity=%d held=%d",
                            requested_slots,
                            max_concurrency,
                            held_slots,
                        )

                    # Reserve as one logical operation so competing multi-slot
                    # tasks cannot each hold a partial reservation forever.
                    with reservation_lock:
                        for _ in range(held_slots):
                            capacity.acquire()
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        for _ in range(held_slots):
                            capacity.release()

                # Thread pool large enough for all tasks to be submitted
                total_tasks = n_joint + n_solo + n_public
                with ThreadPoolExecutor(max_workers=total_tasks) as ex:
                    futures = []

                    # Phase 1: Joint (1 slot each, highest priority)
                    for act in joint_acts + encounter_acts:
                        futures.append(ex.submit(run_with_slots, act.run, 1))

                    # Phase 2: Solo (1 slot each, fast)
                    for act in solo_acts:
                        futures.append(ex.submit(run_with_slots, act.run, 1))

                    # Phase 3: Public (sorted by participant count, small first)
                    # Small Public completes faster, releases slots for others
                    sorted_public = sorted(public_acts, key=lambda a: len(a.agents))
                    for act in sorted_public:
                        n_participants = len(act.agents)
                        slots = max(
                            1,
                            min(
                                n_participants,
                                public_internal_parallelism,
                                max_concurrency,
                            ),
                        )
                        futures.append(
                            ex.submit(run_with_slots, act.run, slots, parallel=True)
                        )

                    # AGENTOPIA_ACTIVITY_BARRIER_V1745
                    # Each model request is bounded in utils.py. A SoloActivity can
                    # legitimately perform several sequential bounded calls, so a
                    # fixed 420-second per-future kill creates false-positive restarts.
                    # Track completion by activity identity and isolate completed
                    # exceptions without terminating the whole persistent world.
                    def _activity_label(act):
                        aid = getattr(act, "activity_id", "unknown")
                        try:
                            names = ",".join(a.name for a in getattr(act, "agents", []))
                        except Exception:
                            names = "unknown"
                        return f"{act.__class__.__name__}:{aid}:{names}"

                    activity_labels = (
                        [_activity_label(a) for a in (joint_acts + encounter_acts)]
                        + [_activity_label(a) for a in solo_acts]
                        + [_activity_label(a) for a in sorted_public]
                    )
                    future_labels = {f: activity_labels[i] for i, f in enumerate(futures)}
                    import time as _activity_time
                    barrier_started = _activity_time.monotonic()
                    for f in as_completed(futures):
                        label = future_labels.get(f, "unknown")
                        try:
                            f.result()
                            self.logger.info(
                                f"[ACTIVITY_RESILIENCE] completed {label} "
                                f"barrier_elapsed={_activity_time.monotonic()-barrier_started:.1f}s"
                            )
                        except Exception as exc:
                            self.logger.exception(
                                f"[ACTIVITY_RESILIENCE] failed {label}: {exc}"
                            )
                            # Fail forward for completed exceptions. The individual
                            # activity is skipped; the rest of Detroit continues.
                            continue
            else:
                # Sequential fallback
                for act in joint_acts + encounter_acts:
                    act.run()
                for act in public_acts:
                    act.run(parallel=False)
                for act in solo_acts:
                    act.run()

        # Review phase
        self.clock.set_stage(Stage.REVIEW)
        t = self.clock.get_time()
        self.logger.info(f"== REVIEW STAGE == year={t.year} week={t.week}")
        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                list(ex.map(lambda a: a.review(), self.agents))
        else:
            for agent in self.agents:
                agent.review()

        # Settle phase (weekly cleanup)
        self.clock.set_stage(Stage.SETTLE)
        t = self.clock.get_time()
        self.logger.info(f"== SETTLE STAGE == year={t.year} week={t.week}")
        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                list(ex.map(lambda a: a.settle_week(), self.agents))
        else:
            for agent in self.agents:
                agent.settle_week()

        # Factions recruit after the normal weekly life cycle. New recruits
        # participate beginning with the next simulated week.
        if getattr(self, "faction_engine", None) is not None:
            self.faction_engine.weekly_tick()

    # Internal --------------------------------------------------------------
    # def _build_today_activities(self) -> tuple[list[JointActivity], list[SoloActivity]]:
    #     """Build today's joint and solo activities based on current clock time."""
    #     t = self.clock.get_time()
    #     # 1) Collect today's joint activities (deduplicated by activity_id)
    #     aid_to_schd: Dict[str, Schedule] = {}
    #     aid_to_agents: Dict[str, set[str]] = {}
    #     for a in self.agents:
    #         schd = a.dm.get_today_schedule()
    #         if not schd:
    #             # agent has no joint activity on this day
    #             continue

    #         at = schd.activity_time
    #         aid = schd.activity_id
    #         assert (at == t) and (schd.type == "joint"), (
    #             f"Invalid schedule for agent {a.name}: {schd} "
    #         )

    #         aid_to_schd.setdefault(aid, schd)
    #         aid_to_agents.setdefault(aid, set()).add(a.name)

    #     # 2) Validate JointActivity (sorted by activity_id for determinism)
    #     name2agent = self.by_name()
    #     joint_acts = []
    #     for aid, schd in sorted(aid_to_schd.items()):
    #         participants = schd.participants

    #         # Validate: 1) at least 2 people; 2) all role names are valid and have agents; 3) participants == agents that have this activity
    #         assert len(participants) >= 2
    #         assert all(n in name2agent for n in participants)

    #         assert set(participants) == aid_to_agents[aid]

    #         p_agents = [name2agent[n] for n in participants]

    #         act = JointActivity.from_schedule(
    #             schd, p_agents, location_store=self.location_store
    #         )
    #         joint_acts.append(act)

    #     # 3) Determine SoloActivity
    #     engaged: set[str] = set()
    #     for aid, schd in sorted(aid_to_schd.items()):
    #         engaged.update(schd.participants)

    #     solo_agents = [ag for ag in self.agents if ag.name not in engaged]
    #     solo_acts = [
    #         SoloActivity(
    #             activity_id=f"{ag.name}-solo-{t}",
    #             activity_name="Solo",
    #             time=t,
    #             agents=[ag],
    #         )
    #         for ag in solo_agents
    #     ]

    #     return joint_acts, solo_acts

    def _build_today_activities_all_types(
        self,
    ) -> tuple[
        list["PublicActivity"],
        list[JointActivity],
        list[JointActivity],
        list[SoloActivity],
    ]:
        """Build today's activities for all types.

        All activity types (joint, public, encounter) are read from agent schedules.
        Agents without any schedule get Solo activity.

        Priority handling (Encounter > Joint > Public) is done in agent.get_schedule().

        Returns:
            Tuple of (public_acts, joint_acts, encounter_acts, solo_acts)
        """
        from src.world.activity import PublicActivity

        t = self.clock.get_time()
        name2agent = self.by_name()

        # Collect schedules grouped by (type, activity_id)
        # type -> activity_id -> (schd, set of agent names)
        schedules_by_type: dict[str, dict[str, tuple[Schedule, set[str]]]] = {
            "joint": {},
            "public": {},
            "encounter": {},
        }

        engaged: set[str] = set()

        for agent in self.agents:
            schd = agent.get_schedule()
            if not schd:
                continue

            at = schd.activity_time
            assert at == t, (
                f"Schedule time mismatch for {agent.name}: expected {t}, got {at}"
            )

            stype = schd.type
            assert stype in schedules_by_type, (
                f"Unknown schedule type '{stype}' for {agent.name}"
            )

            aid = schd.activity_id
            if aid not in schedules_by_type[stype]:
                schedules_by_type[stype][aid] = (schd, set())
            schedules_by_type[stype][aid][1].add(agent.name)
            engaged.add(agent.name)

        # Build activities by type
        def build_joint_or_encounter(stype: str) -> list[JointActivity]:
            """Build Joint or Encounter activities with strict validation."""
            acts = []
            for aid in sorted(schedules_by_type[stype].keys()):
                schd, agent_names = schedules_by_type[stype][aid]
                participants = schd.participants

                # Validation: participants in schedule must match collected agents
                assert len(participants) >= 2, (
                    f"{stype} activity {aid} has < 2 participants: {participants}"
                )
                assert all(n in name2agent for n in participants), (
                    f"{stype} activity {aid} has unknown participants: {participants}"
                )
                assert set(participants) == agent_names, (
                    f"{stype} activity {aid} mismatch: "
                    f"schd.participants={participants}, collected={agent_names}"
                )

                p_agents = [name2agent[n] for n in participants]
                act = JointActivity.from_schedule(
                    schd, p_agents, location_store=self.location_store
                )
                acts.append(act)
            return acts

        def build_public() -> list[PublicActivity]:
            """Build Public activities (min 1 participant).

            Unlike Joint/Encounter where participants are pre-determined,
            Public participants are independently signed up - each agent's
            schedule only contains themselves in participants field.
            We aggregate all sign-ups here.

            Note: If an agent signed up for Public but also has Joint activity,
            Joint takes priority (handled in get_schedule()), so that agent
            won't appear in agent_names here - this is correct behavior.
            """
            acts = []
            for aid in sorted(schedules_by_type["public"].keys()):
                schd, agent_names = schedules_by_type["public"][aid]

                if len(agent_names) < 1:
                    continue

                # Aggregate all sign-ups (each agent's schedule has participants=[self])
                participant_names = sorted(agent_names)
                participant_agents = [name2agent[n] for n in participant_names]

                # Must update participants for downstream (original only has single agent)
                schd.participants = participant_names

                act = PublicActivity.from_schedule(
                    schd, participant_agents, event_description=schd.event_description
                )
                acts.append(act)
            return acts

        public_acts = build_public()
        joint_acts = build_joint_or_encounter("joint")
        encounter_acts = build_joint_or_encounter("encounter")

        # Solo for remaining agents (activity_id auto-generated in __post_init__)
        solo_agents = [ag for ag in self.agents if ag.name not in engaged]
        solo_acts = [
            SoloActivity(
                activity_id=None,
                activity_name="Solo",
                time=t,
                agents=[ag],
            )
            for ag in solo_agents
        ]

        return public_acts, joint_acts, encounter_acts, solo_acts

    # Public Stage Methods ----------------------------------------------------
    def _generate_public_events(self) -> List[PublicEvent]:
        """God Model generates public events for this week.

        1. Load existing events from file (auto-filters expired)
        2. Generate new events via God Model
        3. Persist new events to file
        4. Return list of events active this week (as this-week instances)
        """
        from src.world.god import generate_public_events
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="public_activity")
        t = self.clock.get_time()
        n_weeks_per_year = self.config["time"]["n_week"]
        n_days = self.config["time"]["n_day"]

        # 1. Load existing events (expired ones are filtered out on read)
        public_events = self._load_public_events()

        if verify_logger:
            verify_logger.info(
                f"[VERIFY-PUBLIC] Loaded {len(public_events)} active events from file"
            )

        # 2. Generate new public events
        agent_summaries = self.build_all_agents_summary()
        previous_events = "\n".join(
            [
                f"- {evt.event_name}: {evt.description}"
                for evt in sorted(public_events.values(), key=lambda e: e.event_id)
            ]
        )
        valid_agent_names = [agent.name for agent in self.agents]
        existing_event_names = {
            evt.event_name.strip().lower()
            for evt in public_events.values()
            if evt.is_active_this_week(t.year, t.week, n_weeks_per_year)
        }

        new_events = generate_public_events(
            agent_summaries=agent_summaries,
            previous_events=previous_events,
            n_days=n_days,
            year=t.year,
            week=t.week,
            valid_agent_names=valid_agent_names,
            existing_event_names=existing_event_names,
        )

        # 3. Persist new events to file
        if new_events:
            self._save_public_events(new_events)
            for evt in new_events:
                public_events[evt.event_id] = evt

        if verify_logger:
            verify_logger.info(
                f"[VERIFY-PUBLIC] Generated {len(new_events)} new events: "
                f"{[e.event_name for e in new_events]}"
            )

        self.logger.info(
            f"Public events this week: {len(public_events)} total, {len(new_events)} new"
        )

        # 4. Build this-week instances for active events
        this_week_events: List[PublicEvent] = []
        for evt in public_events.values():
            if not evt.is_active_this_week(t.year, t.week, n_weeks_per_year):
                continue
            this_week_evt = PublicEvent(
                event_id=evt.event_id,
                event_name=evt.event_name,
                start_year=t.year,
                start_week=t.week,
                start_day=evt.start_day,
                repeat_weeks=evt.repeat_weeks,
                description=evt.description,
                eligible_participants=evt.eligible_participants,
            )
            this_week_events.append(this_week_evt)
        this_week_events.sort(key=lambda e: e.event_id)

        return this_week_events

    def _generate_encounter_events(self) -> None:
        """Generate encounter events for idle agents for the whole week.

        Called after confirm_schedule() in AFTER_CONTACT stage.
        Uses God Model to generate meaningful encounters with scene descriptions.
        """
        import hashlib
        import random
        from src.utils import get_verify_logger
        from src.world.god import god_generate_encounter_events

        verify_logger = get_verify_logger(feature="encounter_activity")
        t = self.clock.get_time()
        name2agent = self.by_name()

        # Collect idle agents for each day of the week
        n_days = self.config["time"]["n_day"]
        n_weeks_per_year = self.config["time"]["n_week"]

        # idle_agents_by_day: day -> {agent_name: [related_names]}
        idle_agents_by_day: dict[int, dict[str, list[str]]] = {}
        total_encounters = 0

        for day in range(1, n_days + 1):
            # Find agents with activities on this day (from agent.dm)
            engaged_on_day: set[str] = set()

            for agent in self.agents:
                schd = agent.dm.get_schedule_for_day(t.year, t.week, day)
                if schd:
                    engaged_on_day.add(agent.name)

            # Idle agents (sorted for determinism)
            idle_agents = sorted(
                [a.name for a in self.agents if a.name not in engaged_on_day]
            )

            if len(idle_agents) < 2:
                idle_agents_by_day[day] = {}
                continue

            # Build idle agents info with their top 10 related characters
            day_agents: dict[str, list[str]] = {}
            for agent_name in idle_agents:
                agent = name2agent[agent_name]
                related_names = agent.dm.get_top_related_names(limit=10)
                day_agents[agent_name] = related_names
            idle_agents_by_day[day] = day_agents

            # Calculate number of encounters for this day: x/5 with probabilistic rounding
            x = len(idle_agents)
            n_encounters_float = x / 5.0

            # Deterministic seed for this day
            seed_str = f"Y{t.year}-W{t.week}-D{day}-encounter"
            seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()[:16]
            rng = random.Random(int(seed_hash, 16))

            # Probabilistic rounding
            base = int(n_encounters_float)
            frac = n_encounters_float - base
            n_encounters = base + (1 if rng.random() < frac else 0)
            total_encounters += n_encounters

        if total_encounters == 0:
            self.logger.info("No encounter events to generate this week")
            return

        # Get valid locations from LocationStore (encounters only happen in public places)
        public_locs, _ = self.location_store.list_all()
        valid_locations = sorted(public_locs)

        if not valid_locations:
            raise RuntimeError(
                f"No valid public locations found (location_store.world={self.location_store.world}, "
                f"path={self.location_store.path})"
            )

        # Current time string
        current_time = f"Y{t.year}-W{t.week:02d}"

        # Use God Model to generate all encounters for the week
        encounters = god_generate_encounter_events(
            current_time=current_time,
            n_days=n_days,
            idle_agents_by_day=idle_agents_by_day,
            valid_locations=valid_locations,
            total_encounters=total_encounters,
            agents=self.agents,
        )

        # Create Schedule for each encounter
        # Note: encounters order is deterministic (LLM output cached), no sorting needed
        for enc in encounters:
            participants = enc["participants"]  # Already sorted list
            p1, p2 = participants[0], participants[1]
            day = enc["day"]
            location = enc["location"]
            description = enc["description"]

            activity_time = TimeState(
                year=t.year,
                week=t.week,
                stage=Stage.ACTIVITY,
                day=day,
            )

            # activity_id auto-generated by Schedule.__post_init__
            schd = Schedule(
                activity_name=f"Encounter-{p1}-{p2}",
                activity_time=activity_time,
                participants=participants,
                type="encounter",
                location=location,
                event_description=description,
            )

            # Persist to each participant's schedule
            for agent_name in schd.participants:
                agent = name2agent[agent_name]
                agent.dm.add_schedule(schd)

            if verify_logger:
                verify_logger.info(
                    f"[VERIFY-ENCOUNTER] Created encounter on D{day}: {p1} meets {p2} at {location}"
                )
                verify_logger.info(f"  Scene: {description}")

        self.logger.info(f"Generated {len(encounters)} encounter events for this week")

    # ---------- Year-end Profile Update ----------
    def _update_yearly_profiles(self) -> None:
        """Update profiles for all agents at year end.

        Called after all weeks of a year are complete, before moving to next year.
        GodModel generates new profile based on yearly experiences.
        """
        from src.world.god import update_yearly_profile
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="profile_update")
        current_year = self.clock.get_time().year
        next_year = current_year + 1

        self.logger.info(f"== PROFILE UPDATE == Y{current_year} → Y{next_year}")

        if verify_logger:
            verify_logger.info(
                f"[VERIFY-PROFILE] === PROFILE UPDATE START === "
                f"Y{current_year} → Y{next_year}, {len(self.agents)} agents"
            )

        # Collect results for verification
        results = []

        def update_and_collect(agent):
            result = self._update_agent_profile(agent, current_year, next_year)
            return result

        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                results = list(ex.map(update_and_collect, self.agents))
        else:
            for agent in self.agents:
                results.append(update_and_collect(agent))

        if verify_logger:
            # Log all results
            verify_logger.info("[VERIFY-PROFILE] --- Per-Agent Profile Changes ---")
            for result in sorted(results, key=lambda x: x["agent_name"]):
                name = result["agent_name"]
                changes = result["changes"]
                if changes:
                    verify_logger.info(f"[VERIFY-PROFILE] {name}: {', '.join(changes)}")
                else:
                    verify_logger.info(
                        f"[VERIFY-PROFILE] {name}: no quantitative changes"
                    )

            verify_logger.info(
                f"[VERIFY-PROFILE] === PROFILE UPDATE COMPLETE === "
                f"{len(self.agents)} agents processed"
            )

    def _update_agent_profile(
        self,
        agent: "RoleAgent",
        current_year: int,
        next_year: int,
    ) -> Dict[str, Any]:
        """Update a single agent's profile for next year.

        Args:
            agent: RoleAgent instance
            current_year: Current year number
            next_year: Next year number

        Returns:
            Dict with agent_name and list of changes for verification logging
        """
        from src.world.god import update_yearly_profile
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="profile_update")

        # Read current profile for comparison
        current_profile = agent.dm.read_profile()

        new_profile = update_yearly_profile(agent, current_year, next_year)

        # Faction identity is a world-system field, not something the yearly
        # profile model may silently erase. Preserve it across year changes.
        for persistent_key in ("faction", "world_role", "founding_citizen", "founder_id", "lineage", "origin"):
            if persistent_key in current_profile:
                new_profile[persistent_key] = current_profile[persistent_key]

        agent.dm.write_profile(new_profile, year=next_year)
        self.logger.info(f"Profile updated: {agent.name} for Y{next_year}")

        # Compute changes for verification
        changes = []

        # Personality trait changes
        cur_pq = current_profile["personality_traits"]["quantitative"]
        new_pq = new_profile["personality_traits"]["quantitative"]
        for key in cur_pq:
            if cur_pq[key] != new_pq.get(key):
                changes.append(f"personality.{key}: {cur_pq[key]}→{new_pq[key]}")

        # Talent changes
        cur_tq = current_profile["talents"]["quantitative"]
        new_tq = new_profile["talents"]["quantitative"]
        for key in cur_tq:
            if cur_tq[key] != new_tq.get(key):
                changes.append(f"talents.{key}: {cur_tq[key]}→{new_tq[key]}")

        # Log input summaries (weekly summaries count)
        n_week = self.config["time"]["n_week"]
        summaries = agent.dm.read_weekly_summaries(n_weeks=n_week)

        if verify_logger:
            verify_logger.info(
                f"[VERIFY-PROFILE] {agent.name} INPUT: {len(summaries)} weekly summaries"
            )

        return {"agent_name": agent.name, "changes": changes}

    # Reward Calculation -------------------------------------------------------
    def _calculate_rewards(self) -> None:
        """Periodic calculation of all rewards (objective + subjective + total).

        Called in SETTLE stage when week % period_weeks == 0.
        1. Objective: Social ranking + PageRank
        2. Subjective: God Model evaluation of fulfillment history
        3. Total: Weighted combination
        4. Per-agent save: Store rewards in persona/{name}/reward.jsonl
        Note: Returns and advantages are calculated post-simulation in
        scripts/build_rft_data.py, not during the simulation loop.
        """
        from src.world.reward import (
            # Social
            build_social_graphs,
            calculate_social_rewards,
            compute_social_metrics,
            save_rankings,
            save_social_metrics,
            # Subjective
            compute_subjective_rewards,
            # Total
            calculate_total_rewards,
        )
        from src.utils import get_verify_logger

        verify_logger = get_verify_logger(feature="reward")
        t = self.clock.get_time()

        # Validate: period_weeks should divide n_week evenly
        period_weeks = self.config["reward"]["period_weeks"]
        n_week = self.config["time"]["n_week"]
        if n_week % period_weeks != 0:
            raise ValueError(
                f"period_weeks ({period_weeks}) must divide n_week ({n_week}) evenly"
            )

        self.logger.info(f"== REWARD CALCULATION == year={t.year} week={t.week}")

        # =====================================================================
        # 1. Social Reward (Social Ranking + PageRank)
        # =====================================================================
        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                rankings = list(ex.map(lambda a: a.judge_others(), self.agents))
        else:
            rankings = [a.judge_others() for a in self.agents]

        rankings_by_name = {r.agent_name: r for r in rankings}

        # Persist rankings centrally (PageRank input data for recovery)
        save_rankings(rankings, self.data_dir, t.year, t.week)

        # Compute and save absolute social metrics (cross-run comparable)
        social_metrics = compute_social_metrics(rankings, str(t))
        save_social_metrics(social_metrics, self.data_dir, t.year, t.week)

        affection_graph, respect_graph = build_social_graphs(rankings)

        if not affection_graph and not respect_graph:
            self.logger.warning(
                f"[REWARD] All agents returned empty rankings - no social graph edges."
            )

        social_rewards = calculate_social_rewards(
            affection_graph=affection_graph,
            respect_graph=respect_graph,
            time_str=str(t),
            all_agent_names=[a.name for a in self.agents],
        )

        self.logger.info(f"Social reward: {len(social_rewards)} agents")

        # =====================================================================
        # 2. Subjective Reward (Pure Data-Driven)
        # =====================================================================
        subjective_rewards = compute_subjective_rewards(self.agents, time_str=str(t))
        total_penalties = sum(r.n_penalties for r in subjective_rewards.values())
        self.logger.info(
            f"Subjective reward: {len(subjective_rewards)} agents, "
            f"{total_penalties} misery penalties"
        )

        # =====================================================================
        # 3. Economy Reward (Deposit delta over the past year)
        # =====================================================================
        economy_scores: Dict[str, float] = {}
        for agent in self.agents:
            deposit_start = agent.dm.get_deposit_at_year_start(t.year)
            deposit_end = agent.dm.get_deposit()
            economy_scores[agent.name] = float(deposit_end - deposit_start)

        self.logger.info(f"Economy reward: {len(economy_scores)} agents")

        # =====================================================================
        # 4. Total Reward (Social + Subjective + Economy)
        # =====================================================================
        total_rewards = calculate_total_rewards(
            social_rewards=social_rewards,
            subjective_rewards=subjective_rewards,
            economy_scores=economy_scores,
            time_str=str(t),
        )

        self.logger.info(f"Total reward: {len(total_rewards)} agents")

        # =====================================================================
        # 5. Save Per-Agent Reward Data
        # =====================================================================
        def save_agent_reward(agent):
            ranking = rankings_by_name[agent.name]
            social = social_rewards[agent.name]
            subjective = subjective_rewards[agent.name]
            total = total_rewards[agent.name]
            agent.dm.save_reward(ranking, social, subjective, total)

        if self.parallel:
            with ThreadPoolExecutor(max_workers=pool_size(len(self.agents))) as ex:
                list(ex.map(save_agent_reward, self.agents))
        else:
            for agent in self.agents:
                save_agent_reward(agent)

        # =====================================================================
        # 6. Verification Logging
        # =====================================================================
        if verify_logger:
            verify_logger.info(
                f"[VERIFY-REWARD] === REWARD CALCULATION START === Y{t.year}-W{t.week}"
            )
            verify_logger.info(
                f"[VERIFY-REWARD] Config: period_weeks={period_weeks}, "
                f"n_agents={len(self.agents)}"
            )

            # Log social graph edges
            total_affection_edges = sum(len(v) for v in affection_graph.values())
            total_respect_edges = sum(len(v) for v in respect_graph.values())
            verify_logger.info(
                f"[VERIFY-REWARD] Social graphs: "
                f"affection={total_affection_edges} edges, "
                f"respect={total_respect_edges} edges"
            )

            # Log each agent's ranking input and reward output
            verify_logger.info("[VERIFY-REWARD] --- Per-Agent Details ---")
            for name in sorted(rankings_by_name.keys()):
                ranking = rankings_by_name[name]
                soc = social_rewards[name]
                subj = subjective_rewards[name]
                tot = total_rewards[name]

                # Input: scores
                aff_top = sorted(
                    ranking.affection_scores.items(), key=lambda x: (-x[1], x[0])
                )[:5]
                resp_top = sorted(
                    ranking.respect_scores.items(), key=lambda x: (-x[1], x[0])
                )[:5]
                verify_logger.info(
                    f"[VERIFY-REWARD] {name} INPUT: "
                    f"affection_top5={aff_top}, respect_top5={resp_top}"
                )

                # Output: scores
                verify_logger.info(
                    f"[VERIFY-REWARD] {name} OUTPUT: "
                    f"social(aff={soc.affection_score:.3f}, resp={soc.respect_score:.3f}, "
                    f"combined={soc.combined_score:.3f}), "
                    f"subj(score={subj.score:.3f}, penalties={subj.n_penalties}), "
                    f"total={tot.total_score:.3f}"
                )

            verify_logger.info(
                f"[VERIFY-REWARD] === REWARD CALCULATION COMPLETE === "
                f"total_penalties={total_penalties}"
            )
