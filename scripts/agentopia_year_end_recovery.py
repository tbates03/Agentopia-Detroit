"""Agentopia Detroit 52-week rollover recovery v1.

Installed only into PersistentDetroitWorld. Never changes checkpoint directly.
Reuses previously completed year+1 profiles; failed LLM generation carries the
prior year's profile forward unchanged and records the exception category.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import threading
from datetime import datetime, timezone

MARKER = 'AGENTOPIA_YEAR_END_RECOVERY_V1'


def _validated_profile(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get('personality_traits'), dict)
        and isinstance(value['personality_traits'].get('quantitative'), dict)
        and isinstance(value.get('talents'), dict)
        and isinstance(value['talents'].get('quantitative'), dict)
        and isinstance(value.get('position'), dict)
    )


def _atomic_json_new(path: Path, value: dict) -> None:
    """Write only a genuinely missing year profile, atomically."""
    if path.exists():
        raise FileExistsError(f'Existing 2046 profile will not be overwritten: {path.name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.rollover-' + str(os.getpid()) + '-' + str(threading.get_ident()) + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as fp:
            json.dump(value, fp, indent=4, ensure_ascii=False)
            fp.write('\n')
            fp.flush()
            os.fsync(fp.fileno())
        if path.exists():
            raise FileExistsError(f'Profile appeared during update: {path.name}')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def install(world_class, root: Path, world: Path) -> None:
    """Install tightly scoped rollover hooks before constructing the World."""
    from src.world import world as core_world
    from src.world.clock import Stage

    root = Path(root)
    world = Path(world)
    parent_init = world_class.__init__
    parent_resolve = world_class._resolve_resume_point

    def at_completed_year_end(self) -> bool:
        cp = self._read_checkpoint()
        try:
            return (
                isinstance(cp, dict)
                and int(cp['week']) == int(self.config['time']['n_week'])
                and int(cp['year']) >= int(self.config['time']['start_year'])
            )
        except (KeyError, ValueError, TypeError):
            return False

    def rollover_init(self, *args, **kwargs):
        # Only skip cleanup when the persisted checkpoint proves the final week
        # was completed. This avoids destructive trimming of already committed
        # Week 52 journal records on repeated year-end restarts.
        cp_path = world / 'checkpoint.json'
        try:
            cp = json.loads(cp_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cp = {}
        cfg_path = world / 'config.json'
        try:
            cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
            n_week = int(cfg['world']['time']['n_week'])
        except (OSError, ValueError, KeyError, TypeError):
            n_week = None
        skip_cleanup = (isinstance(cp, dict) and n_week is not None
                        and cp.get('week') == n_week and isinstance(cp.get('year'), int))
        if not skip_cleanup:
            return parent_init(self, *args, **kwargs)

        original_cleanup = core_world.clean_append_only_jsonl_before
        def year_end_no_cleanup(*, world_name, start_time):
            if world_name != 'detroit_persistent':
                raise RuntimeError('Refusing to skip cleanup for a non-Detroit world')
            # Only this completed-week state permits cleanup bypass.
            return None
        core_world.clean_append_only_jsonl_before = year_end_no_cleanup
        try:
            result = parent_init(self, *args, **kwargs)
        finally:
            core_world.clean_append_only_jsonl_before = original_cleanup
        self.logger.warning('[YEAR_END_RECOVERY] %s committed; preserved Week 52 journals',
                            str(cp))
        return result

    def resolve_after_completed_week(self, resume_from):
        year, week = parent_resolve(self, resume_from)
        if resume_from is None and at_completed_year_end(self):
            n_week = int(self.config['time']['n_week'])
            self._year_end_resume_from = (year, n_week + 1)
            return (year, n_week + 1)
        return (year, week)

    def update_profiles_resumable(self):
        from src.world.god import update_yearly_profile
        from concurrent.futures import ThreadPoolExecutor, as_completed

        current_year = self.clock.get_time().year
        next_year = current_year + 1
        n_week = int(self.config['time']['n_week'])
        # If no weekly step ran on a completed-week restart, restore exact
        # week-end clock semantics for diaries, rewards, and profile prompts.
        if int(self.clock.get_time().week) != n_week:
            self.clock.set_week(n_week)
            self.clock.set_stage(Stage.SETTLE)
        elif self.clock.get_time().stage != Stage.SETTLE:
            self.clock.set_stage(Stage.SETTLE)

        self.logger.info('== PROFILE UPDATE == Y%d -> Y%d [RESUMABLE]', current_year, next_year)
        receipt_path = root / 'runtime' / 'year_end_recovery' / f'Y{current_year}.json'
        receipt_lock = threading.Lock()
        counts = {'existing': 0, 'generated': 0, 'carried_forward': 0}
        fallbacks = {}
        total = len(self.agents)

        def snapshot_receipt():
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                'schema': MARKER,
                'source_year': current_year,
                'target_year': next_year,
                'status': 'profiles_in_progress',
                'expected_active_profiles': total,
                'counts': dict(counts),
                'fallbacks': dict(fallbacks),
                'updated_utc': datetime.now(timezone.utc).isoformat(),
            }
            tmp = receipt_path.with_name(receipt_path.name + '.' + str(os.getpid()) + '.tmp')
            with tmp.open('w', encoding='utf-8') as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, receipt_path)

        def handle_agent(agent):
            name = agent.name
            dest = world / 'persona' / name / 'profile' / f'year={next_year}.json'
            if dest.exists():
                try:
                    existing = json.loads(dest.read_text(encoding='utf-8'))
                except Exception as exc:
                    raise RuntimeError(f'Existing target profile could not be read: {type(exc).__name__}') from exc
                if not _validated_profile(existing):
                    raise RuntimeError('Existing target profile is invalid. Refusing to overwrite or bypass.')
                status, error = 'existing', None
            else:
                prior = agent.dm.read_profile()
                if not _validated_profile(prior):
                    raise RuntimeError('Source profile missing required fields; refusing carry-forward')
                error = None
                try:
                    new = update_yearly_profile(agent, current_year, next_year)
                    if not _validated_profile(new):
                        raise ValueError('Invalid yearly AI profile response')
                    status = 'generated'
                except Exception as exc:
                    # Durable continuity without fabricating personality, identity,
                    # position or achievements. The exact previous profile is used.
                    new = copy.deepcopy(prior)
                    status = 'carried_forward'
                    error = type(exc).__name__
                for field in ('faction', 'world_role', 'founding_citizen',
                              'founder_id', 'lineage', 'origin'):
                    if field in prior:
                        new[field] = copy.deepcopy(prior[field])
                _atomic_json_new(dest, new)
                self.logger.info('[YEAR_END_RECOVERY] Y%d profile %s: %s',
                                 next_year, name, status)

            with receipt_lock:
                counts[status] += 1
                if error is not None:
                    fallbacks[name] = error
                    self.logger.warning('[YEAR_END_RECOVERY] %s carried forward: %s', name, error)
                snapshot_receipt()

        # Bound annual throughput independently from citizen slots, so long
        # profile prompts cannot saturate the local model pool.
        pool = min(4, max(1, int(self.max_concurrency)), max(1, total))
        with ThreadPoolExecutor(max_workers=pool) as executor:
            futures = [executor.submit(handle_agent, a) for a in self.agents]
            failures = []
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as exc:
                    failures.append(type(exc).__name__ + ': ' + str(exc)[:140])
        if failures:
            raise RuntimeError('Annual update blocked by ' + str(len(failures))
                               + ' nonrecoverable profile errors: ' + '; '.join(failures[:3]))

        # Validate every active member has a readable next-year profile.
        for a in self.agents:
            path = world / 'persona' / a.name / 'profile' / f'year={next_year}.json'
            if not path.exists() or not _validated_profile(json.loads(path.read_text(encoding='utf-8'))):
                raise RuntimeError('Missing/invalid target profile prevents year commit')

        with receipt_lock:
            snapshot_receipt()
            result = json.loads(receipt_path.read_text(encoding='utf-8'))
            result['status'] = 'profiles_complete_reward_pending'
            tmp = receipt_path.with_name(receipt_path.name + '.' + str(os.getpid()) + '.tmp')
            with tmp.open('w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, receipt_path)
        self.logger.info('[YEAR_END_RECOVERY] %d/%d active profiles ready (reused=%d generated=%d carried=%d). Continuing rewards.',
                         sum(counts.values()), total, counts['existing'],
                         counts['generated'], counts['carried_forward'])

    world_class.__init__ = rollover_init
    world_class._resolve_resume_point = resolve_after_completed_week
    world_class._update_yearly_profiles = update_profiles_resumable
