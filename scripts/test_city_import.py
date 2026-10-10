#!/usr/bin/env python3
"""Offline tests for City Builder isolated staged import."""
import json
import tempfile
import unittest
from pathlib import Path

from import_city_manifest import stage, validate_manifest


def example(world="chicago"):
    return {
        "schema": "agentopia.city.manifest.v1", "world_id": world,
        "display_name": "Chicago", "country": "United States", "region": "Illinois",
        "location": {"latitude": 41.88, "longitude": -87.63},
        "timezone": "America/Chicago", "climate_profile": "temperate",
        "notes": "", "provenance": [],
        "geography": {"street_names": ["Michigan Avenue", "Michigan Avenue", "State Street"],
                      "neighborhood_names": ["Loop"],
                      "named_places": ["Chicago Public Library"]},
        "deployment": {"mode": "staging_only", "does_not_modify_active_world": True},
    }


class CityImportTests(unittest.TestCase):
    def test_preview_and_isolated_import(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            manifest = root / "input.json"
            manifest.write_text(json.dumps(example()), encoding="utf-8")
            target_root = root / "private_staging"
            preview = stage(manifest, target_root, dry_run=True)
            self.assertFalse(target_root.exists())
            self.assertFalse(preview["launch_ready"])
            self.assertEqual(preview["counts"]["street_names"], 2)
            report = stage(manifest, target_root)
            directory = target_root / "city_chicago"
            self.assertTrue((directory / "DO_NOT_LAUNCH.txt").exists())
            self.assertEqual(json.loads((directory / "profile.json").read_text())["world_id"], "chicago")
            self.assertEqual(len(json.loads((directory / "geography.json").read_text())["streets"]), 2)
            self.assertEqual(report["status"], "STAGED_ONLY")
            with self.assertRaises(FileExistsError):
                stage(manifest, target_root)
            self.assertTrue((directory / "manifest.json").exists())

    def test_reject_detroit(self):
        with self.assertRaises(ValueError):
            validate_manifest(example("detroit"))

    def test_reject_traversal_and_non_staging(self):
        for bad in ("../detroit_persistent", "x/y", "..", "-oops"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_manifest(example(bad))
        wrong = example()
        wrong["deployment"]["mode"] = "launch"
        with self.assertRaises(ValueError):
            validate_manifest(wrong)

    def test_reject_bad_geography(self):
        wrong = example()
        wrong["geography"]["street_names"] = ["ok", None]
        with self.assertRaises(ValueError):
            validate_manifest(wrong)


if __name__ == "__main__":
    unittest.main()
