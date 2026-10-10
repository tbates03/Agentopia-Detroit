#!/usr/bin/env python3
"""End-to-end offline tests for a Chicago/Flint isolated activity sandbox."""
import json
import tempfile
import unittest
from pathlib import Path
from import_city_manifest import stage
from run_city_sandbox import initialize, advance, read, clock

def manifest(id):
    return {
        "schema":"agentopia.city.manifest.v1","world_id":id,
        "display_name":id.title(),"country":"United States",
        "location":{"latitude":41.88,"longitude":-87.63},
        "geography":{"street_names":["Main Street"],"neighborhood_names":["Downtown"],
                     "named_places":["Library","School"]},
        "deployment":{"mode":"staging_only","does_not_modify_active_world":True},
        "provenance":[]}

class SandboxTests(unittest.TestCase):
    def test_two_cities_independent_restart_replay_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            worlds=[]
            for name in ("chicago","flint"):
                source=root/(name+".json")
                source.write_text(json.dumps(manifest(name)),encoding="utf-8")
                stage(source,root/"imports")
                world=root/"imports"/("city_"+name)
                worlds.append(world)
                initialize(world,6)
            chicago,flint=worlds
            self.assertEqual(read(chicago)["tick"],0)
            advance(chicago,3)
            self.assertEqual(read(chicago)["tick"],3)
            self.assertEqual(read(flint)["tick"],0)
            state=read(chicago)
            self.assertEqual(state["time"],clock(3))
            self.assertEqual(len(state["residents"]),6)
            self.assertTrue(all(x["activity"] for x in state["residents"]))
            self.assertTrue(len(state["recent_events"])>0)
            # Simulated restart: state is loaded from disk, never reinitialized.
            self.assertEqual(read(chicago)["tick"],3)
            with self.assertRaises(FileExistsError):
                initialize(chicago)
            first=read(chicago)["recent_events"]
            advance(chicago,1)
            self.assertEqual(len(set(x["id"] for x in read(chicago)["recent_events"])),24)
            self.assertEqual(read(chicago)["recent_events"][:len(first)],first)
            self.assertEqual(read(flint)["tick"],0)

    def test_clock_year_transition(self):
        self.assertEqual(clock(1),{"year":2045,"week":1,"day":1,"stage":"morning"})
        self.assertEqual(clock(52*7*4+1)["year"],2046)

if __name__=="__main__":
    unittest.main()
