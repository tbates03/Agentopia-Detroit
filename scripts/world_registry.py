#!/usr/bin/env python3
"""Read-only world registry and guarded foreground launcher for isolated city sandboxes."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from run_city_sandbox import stage, read

ROOT = Path(__file__).resolve().parents[1]
CITY_ROOT = ROOT / "data" / "city_imports"
DETROIT = ROOT / "data" / "detroit_persistent"

def resolve(world_id, city_root=CITY_ROOT):
    import re
    if not isinstance(world_id,str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}",world_id) or world_id in ("detroit","detroit-persistent"):
        raise ValueError("Invalid or reserved world identifier")
    base = Path(city_root).expanduser().resolve()
    if base == DETROIT.resolve() or DETROIT.resolve() in base.parents:
        raise ValueError("City directory overlaps protected Detroit")
    folder = base / ("city_" + world_id)
    if folder.is_symlink() or folder.resolve().parent != base:
        raise ValueError("City folder must be a non-symlink direct child")
    path,manifest,_ = stage(folder)
    if manifest["world_id"] != world_id:
        raise ValueError("World identity mismatch")
    return path

def list_worlds(city_root=CITY_ROOT):
    base = Path(city_root).expanduser().resolve()
    worlds = [{"id":"detroit","mode":"protected","managed_launch":False}]
    if base == DETROIT.resolve() or DETROIT.resolve() in base.parents:
        raise ValueError("City directory overlaps protected Detroit")
    if base.exists():
        for item in sorted(base.glob("city_*")):
            try:
                path=resolve(item.name[5:],base)
                try:
                    state=read(path)
                    worlds.append({"id":item.name[5:],"mode":"initialized","tick":state["tick"],"managed_launch":True})
                except FileNotFoundError:
                    worlds.append({"id":item.name[5:],"mode":"staged","managed_launch":False})
            except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
                worlds.append({"id":item.name[5:],"mode":"invalid","managed_launch":False})
    return {"schema":"agentopia.world.registry.v2","worlds":worlds}

def plan(world_id,city_root=CITY_ROOT,port=8777,interval=3):
    folder=resolve(world_id,city_root)
    snapshot=read(folder)
    if not isinstance(port,int) or not (1024<=port<=65535) or port==8766:
        raise ValueError("Invalid port or Detroit observer port")
    if not isinstance(interval,int) or not (1<=interval<=3600):
        raise ValueError("Interval must be 1-3600 seconds")
    return {"world_id":world_id,"path":str(folder),"tick":snapshot["tick"],
            "command":[sys.executable,str(ROOT/"scripts"/"run_city_sandbox.py"),
                       "run",str(folder),"--port",str(port),"--interval",str(interval)]}

def main():
    ap=argparse.ArgumentParser(description="City world registry; Detroit engine protected")
    ap.add_argument("action",choices=("list","validate","launch"))
    ap.add_argument("--world")
    ap.add_argument("--city-root",type=Path,default=CITY_ROOT)
    ap.add_argument("--port",type=int,default=8777)
    ap.add_argument("--interval",type=int,default=3)
    ap.add_argument("--execute",action="store_true",help="Run independent city sandbox in foreground")
    args=ap.parse_args()
    try:
        if args.action=="list": out=list_worlds(args.city_root)
        elif not args.world: raise ValueError("--world required")
        elif args.action=="validate": out={"ok":True,"path":str(resolve(args.world,args.city_root))}
        else:
            out=plan(args.world,args.city_root,args.port,args.interval)
            if args.execute:
                raise SystemExit(subprocess.call(out["command"],cwd=str(ROOT)))
        print(json.dumps(out,indent=2))
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        ap.exit(2,"ERROR: "+str(exc)+"\n")

if __name__=="__main__":
    main()
