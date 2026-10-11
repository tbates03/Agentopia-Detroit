#!/usr/bin/env python3
"""Bounded, advisory cognitive escalation policy.

This module does not launch a model or change the running world. A deep model
may only be attached after latency/queue and memory-pressure gates are tested.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any

HIGH_IMPACT = {'faction_campaign', 'defensive_response', 'life_decision', 'city_emergency'}
CYBER = {'faction_campaign', 'defensive_response', 'cyber_incident'}


@dataclass(frozen=True)
class Decision:
    lane: str
    escalation: bool
    score: float
    reason: str
    budget_tokens: int


def decide(event: dict[str, Any], *, deep_model_available: bool = False,
           memory_pressure: str = 'unknown', queue_depth: int = 0,
           queue_limit: int = 2) -> Decision:
    """Choose a lane from trusted world-event metadata, never raw model prose.

    Input event values are advisory: classification never writes world state.
    `memory_pressure` must be green to enable optional expensive inference.
    """
    kind = str(event.get('kind', 'routine'))
    def normalized(key: str) -> float:
        try:
            return max(0.0, min(1.0, float(event.get(key, 0.0))))
        except (TypeError, ValueError):
            return 0.0
    score = round(0.40 * normalized('importance') +
                  0.30 * normalized('uncertainty') +
                  0.30 * normalized('consequence'), 3)
    high = kind in HIGH_IMPACT and score >= 0.70
    pressure_ok = memory_pressure.lower() == 'green'
    queue_ok = queue_depth <= queue_limit and queue_depth >= 0
    if high and deep_model_available and pressure_ok and queue_ok:
        return Decision('deep_reasoning', True, score, 'high-impact event passed pressure and queue gates', 2048)
    if kind in CYBER:
        reason = 'cyber specialist; deep reasoning unavailable or throttled' if high else 'cyber-specific task'
        return Decision('cyber', False, score, reason, 1024)
    if high or score >= 0.70:
        return Decision('strategy', False, score, 'moderate or high-complexity planning', 1024)
    return Decision('citizen', False, score, 'routine work stays on smaller models', 256)


def demo() -> dict[str, Any]:
    cases = {
        'obsidian_guardians': {'kind': 'defensive_response', 'importance': 0.9, 'uncertainty': 0.8, 'consequence': 0.9},
        'citizen_career_change': {'kind': 'life_decision', 'importance': 0.8, 'uncertainty': 0.8, 'consequence': 0.8},
        'citywide_infrastructure': {'kind': 'city_emergency', 'importance': 1.0, 'uncertainty': 0.9, 'consequence': 1.0},
        'routine_conversation': {'kind': 'routine', 'importance': 0.1, 'uncertainty': 0.1, 'consequence': 0.1},
    }
    return {key: asdict(decide(case, deep_model_available=True, memory_pressure='green'))
            for key, case in cases.items()}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo', action='store_true')
    args = ap.parse_args()
    if args.demo:
        print(json.dumps(demo(), indent=2))
    else:
        print('Advisory policy only; run --demo for example decisions.')
