#!/usr/bin/env python3
"""Synthetic-only tests: no real simulation state is edited or published."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from export_world_beacon import build_beacon
from world_league_live import league_snapshot


class LiveLeagueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "research" / "submissions").mkdir(parents=True)
        self.world = self.root / "data" / "detroit_persistent"
        (self.world / "persona").mkdir(parents=True)
        (self.world / "persona" / "Agent_1").mkdir()
        (self.world / "persona" / "Agent_2").mkdir()
        (self.world / "persona" / "Agent_2" / "_background.json").write_text("{}")
        self.profile = {
            "world_id": "detroit", "world_name": "Agentopia Detroit",
            "maintainer": {"github": "tbates03"},
            "repository": "https://github.com/tbates03/Agentopia-Detroit",
            "simulated_context": {"languages": [{"bcp47": "en-US", "name": "English"}]},
            "consent": {"public_research_evaluation": True},
            "simulation_start_year": 2045, "weeks_per_year": 52,
        }
        (self.root / "research" / "submissions" / "detroit.json").write_text(json.dumps({
            **self.profile, "progress": {"weeks_completed": 4, "checkpoint_year": 2045, "checkpoint_week": 4}}))
        (self.world / "config.json").write_text(json.dumps({"world": {"time": {"start_year": 2045, "n_week": 52}}}))
        self.set_checkpoint(2045, 11)

    def set_checkpoint(self, year, week):
        (self.world / "checkpoint.json").write_text(json.dumps({"year": year, "week": week}))

    def test_live_checkpoint_overrides_stale_published_submission(self):
        data = league_snapshot(self.root)
        self.assertTrue(data["live_checkpoint_available"])
        self.assertEqual(data["worlds"][0]["weeks_completed"], 11)
        self.assertEqual(data["worlds"][0]["source"], "live_committed_checkpoint")
        self.assertEqual(data["worlds"][0]["population"], {"total": 2, "active": 1})

    def test_change_checkpoint_automatically_changes_rank_progress(self):
        self.set_checkpoint(2045, 12)
        self.assertEqual(league_snapshot(self.root)["worlds"][0]["weeks_completed"], 12)

    def test_crosses_year_boundary_using_52_week_year(self):
        self.set_checkpoint(2046, 3)
        self.assertEqual(build_beacon(self.root)["progress"]["weeks_completed"], 55)

    def test_missing_checkpoint_shows_published_stale_not_live(self):
        (self.world / "checkpoint.json").unlink()
        data = league_snapshot(self.root)
        self.assertFalse(data["live_checkpoint_available"])
        self.assertEqual(data["worlds"][0]["weeks_completed"], 4)
        self.assertEqual(data["worlds"][0]["source"], "published_submission")

    def test_no_private_agent_data_leaks(self):
        (self.world / "persona" / "Agent_1" / "secret_chat.jsonl").write_text("PRIVATE CHAT SECRET")
        beacon = build_beacon(self.root)
        self.assertNotIn("PRIVATE CHAT SECRET", json.dumps(beacon))
        self.assertNotIn("Agent_1", json.dumps(beacon))

    def test_checkpoint_validation_rejects_incomplete_records(self):
        self.set_checkpoint(2045, -1)
        with self.assertRaises(ValueError):
            build_beacon(self.root)


if __name__ == "__main__":
    unittest.main()
