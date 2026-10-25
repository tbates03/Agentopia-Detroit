"""Agentopia Detroit horizon guard, inclusive 2045..9999.

This is a thin compatibility layer over the installed 2046 year-end recovery.
It does not replace the simulator, change population data, or fabricate time.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone

MARKER = 'AGENTOPIA_YEAR_9999_GUARD_V1'
LAST_YEAR = 9999


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def install(world_class, root: Path, world: Path) -> None:
    """Enforce the finite calendar horizon; leave annual transition logic intact."""
    root = Path(root)
    world = Path(world)
    if getattr(world_class, '_agentopia_year_9999_guard', False):
        return

    previous_run = world_class.run
    previous_write_checkpoint = world_class._write_checkpoint
    previous_update_yearly_profiles = world_class._update_yearly_profiles
    terminal = root / 'runtime' / 'year_end_recovery' / 'terminal_Y9999.json'

    def checkpoint_value():
        try:
            value = json.loads((world / 'checkpoint.json').read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def completed_terminal():
        cp = checkpoint_value()
        if cp != {'year': LAST_YEAR, 'week': 52} or not terminal.is_file():
            return False
        try:
            value = json.loads(terminal.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        return (
            isinstance(value, dict)
            and value.get('schema') == MARKER
            and value.get('status') == 'horizon_complete'
            and value.get('year') == LAST_YEAR
            and value.get('final_week') == 52
        )

    def guarded_run(self):
        year = int(self._resume_year)
        if year > LAST_YEAR:
            raise RuntimeError('Simulation checkpoint exceeds configured year-9999 horizon')
        if year == LAST_YEAR and completed_terminal():
            self.logger.info('[YEAR_9999] Previously finalized horizon. No replay or future-year mutation.')
            return 'horizon_complete'
        result = previous_run(self)
        if year == LAST_YEAR:
            if not completed_terminal():
                raise RuntimeError('Year 9999 returned without durable terminal marker')
            self.logger.info('[YEAR_9999] Final year fully settled. World parked at Y9999-W52.')
            return 'horizon_complete'
        return result

    def guarded_update_yearly_profiles(self):
        year = int(self.clock.get_time().year)
        if year > LAST_YEAR:
            raise RuntimeError('Refusing to generate year-10001 profiles')
        if year == LAST_YEAR:
            # Completed-week recovery may skip all weekly steps and leave Clock
            # at W00. Restore the final-week settle context BEFORE rewards.
            from src.world.clock import Stage
            if int(self.clock.get_time().week) != 52:
                self.clock.set_week(52)
            self.clock.set_stage(Stage.SETTLE)
            self.logger.info('[YEAR_9999] Final-year rewards use Y9999-W52-SETTLE; no year-10000 profiles.')
            return None
        return previous_update_yearly_profiles(self)

    def guarded_write_checkpoint(self, year, week):
        year = int(year)
        week = int(week)
        if year > LAST_YEAR:
            if year != LAST_YEAR + 1 or week != 0:
                raise RuntimeError('Invalid checkpoint beyond year 9999')
            if int(self.clock.get_time().year) != LAST_YEAR:
                raise RuntimeError('Unexpected out-of-range checkpoint request')
            if checkpoint_value() != {'year': LAST_YEAR, 'week': 52}:
                raise RuntimeError('Refusing to finalize 9999 without the completed final week')
            # World.run writes next-year checkpoint ONLY AFTER yearly rewards.
            _write_atomic(terminal, {
                'schema': MARKER,
                'status': 'horizon_complete',
                'year': LAST_YEAR,
                'final_week': 52,
                'final_checkpoint': {'year': LAST_YEAR, 'week': 52},
                'completed_utc': datetime.now(timezone.utc).isoformat(),
            })
            self.logger.info('[YEAR_9999] Final rewards completed; terminal marker committed. Checkpoint remains Y9999-W52.')
            return None
        if year < 1 or not (0 <= week <= 52):
            raise RuntimeError('Invalid world checkpoint coordinates')
        return previous_write_checkpoint(self, year, week)

    world_class.run = guarded_run
    world_class._write_checkpoint = guarded_write_checkpoint
    world_class._update_yearly_profiles = guarded_update_yearly_profiles
    world_class._agentopia_year_9999_guard = True
