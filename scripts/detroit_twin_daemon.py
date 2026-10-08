#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; WORLD=ROOT/'data'/'detroit_persistent'; CP=WORLD/'checkpoint.json'; PID=ROOT/'runtime'/'detroit-twin.pid'
PID.parent.mkdir(parents=True,exist_ok=True); PID.write_text(str(__import__('os').getpid()))
last=None
subprocess.run([sys.executable,str(ROOT/'scripts'/'detroit_digital_twin.py'),'init'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
  while True:
    try: key=CP.read_text(encoding='utf-8') if CP.exists() else '{}'
    except Exception:key='{}'
    if key!=last:
      subprocess.run([sys.executable,str(ROOT/'scripts'/'detroit_digital_twin.py'),'tick'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);last=key
    time.sleep(4)
finally:
  try:PID.unlink()
  except OSError:pass
