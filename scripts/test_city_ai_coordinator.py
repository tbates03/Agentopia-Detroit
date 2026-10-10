#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path
from import_city_manifest import stage
from run_city_sandbox import initialize, read
from city_ai_coordinator import advice, validate_url

class Tests(unittest.TestCase):
    def test_two_cities_and_no_canonical_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            for city in ("chicago","flint"):
                manifest={"schema":"agentopia.city.manifest.v1","world_id":city,"display_name":city,"country":"USA","location":{"latitude":41,"longitude":-83},"geography":{"street_names":["Main"],"neighborhood_names":["Central"],"named_places":["Library"]},"deployment":{"mode":"staging_only","does_not_modify_active_world":True},"provenance":[]}
                path=root/(city+".json");path.write_text(json.dumps(manifest))
                stage(path,root/"worlds")
                folder=root/"worlds"/("city_"+city)
                initialize(folder,3)
                old=(folder/"sandbox_runtime"/"state.json").read_bytes()
                proposal=advice(folder,2,dry_run=False,client=lambda _:{"choices":[{"message":{"content":json.dumps({"action":"study"})}}]})
                self.assertEqual(proposal["world_id"],city)
                self.assertEqual(len(proposal["decisions"]),2)
                self.assertTrue(all(d["source"]=="local-model" for d in proposal["decisions"]))
                self.assertEqual(old,(folder/"sandbox_runtime"/"state.json").read_bytes())
                self.assertEqual(advice(folder,2,dry_run=False)["decision_id"],proposal["decision_id"])
                self.assertEqual(read(folder)["tick"],0)
    def test_reject_remote_and_invalid_model_output(self):
        for endpoint in ("https://example.com/v1/chat/completions","http://127.0.0.1:8081/health","http://127.0.0.1:8081/v1/chat/completions?foo=1"):
            with self.assertRaises(ValueError):
                validate_url(endpoint)
if __name__=="__main__":
    unittest.main()
