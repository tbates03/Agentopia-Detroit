#!/usr/bin/env python3
import json,tempfile,unittest
from pathlib import Path
from import_city_manifest import stage
from run_city_sandbox import initialize
from world_registry import resolve,list_worlds,plan
class Tests(unittest.TestCase):
 def test_registry_isolation(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); base=root/"worlds"
   for name in ("chicago","flint"):
    data={"schema":"agentopia.city.manifest.v1","world_id":name,"display_name":name,"country":"US","location":{"latitude":40,"longitude":-80},"geography":{"street_names":[],"neighborhood_names":[],"named_places":[]},"deployment":{"mode":"staging_only","does_not_modify_active_world":True}}
    source=root/(name+".json");source.write_text(json.dumps(data));stage(source,base)
    initialize(base/("city_"+name),3)
   result=list_worlds(base)
   self.assertEqual([x["id"] for x in result["worlds"]],["detroit","chicago","flint"])
   self.assertFalse(result["worlds"][0]["managed_launch"])
   self.assertTrue(result["worlds"][1]["managed_launch"])
   self.assertNotEqual(plan("chicago",base)["path"],plan("flint",base)["path"])
   with self.assertRaises(ValueError): resolve("detroit",base)
   with self.assertRaises(ValueError): resolve("../detroit",base)
   with self.assertRaises(ValueError): plan("chicago",base,8766)
   (base/"city_evade").symlink_to(base/"city_chicago",target_is_directory=True)
   with self.assertRaises(ValueError):resolve("evade",base)
if __name__=="__main__":unittest.main()
