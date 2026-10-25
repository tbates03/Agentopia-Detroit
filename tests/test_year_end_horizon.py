"""Offline regression checks; never starts or modifies the Detroit persistent world."""
import ast
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
class HorizonSourceTests(unittest.TestCase):
    def test_sources_compile(self):
        for name in ("agentopia_year_end_recovery.py", "agentopia_year_9999_guard.py",
                     "run_detroit_persistent.py", "detroit_world_context.py"):
            path = ROOT / "scripts" / name
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
    def test_runner_integration(self):
        source = (ROOT/"scripts"/"run_detroit_persistent.py").read_text()
        self.assertIn("_agentopia_year_end_recovery.install(PersistentDetroitWorld, ROOT, WORLD)", source)
        self.assertIn("_agentopia_9999.install(PersistentDetroitWorld, ROOT, WORLD)", source)
        self.assertIn("9999 - start + 1", source)
        self.assertIn('if _cycle_result == "horizon_complete":', source)
        self.assertIn('if _cycle_result == "year_complete":', source)
    def test_year_9999_week_52_calendar(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from detroit_world_context import week_dates
        dates = week_dates(9999,52)
        self.assertEqual((len(dates), dates[0], dates[-1]), (7,date(9999,12,25),date(9999,12,31)))
        for year in (2045,2046,2099,2100,9998):
            for week in (1,52):
                self.assertEqual(len(week_dates(year,week)),7)
    def test_guards_expose_hooks(self):
        for name in ("agentopia_year_end_recovery.py", "agentopia_year_9999_guard.py"):
            tree=ast.parse((ROOT/"scripts"/name).read_text())
            self.assertTrue(any(isinstance(x,ast.FunctionDef) and x.name=="install" for x in tree.body))
if __name__ == "__main__":
    unittest.main()
