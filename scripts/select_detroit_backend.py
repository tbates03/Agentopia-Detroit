#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/'data'/'detroit_persistent'
CFG=WORLD/'config.json'
FALLBACK=WORLD/'backend_ollama_fallback.json'
def read(p,d):
    try: return json.loads(p.read_text(encoding='utf-8')) if p.exists() else d
    except Exception: return d
def write(p,o):
    t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8'); t.replace(p)
ap=argparse.ArgumentParser(); ap.add_argument('mode',choices=['llama','ollama']); a=ap.parse_args()
cfg=read(CFG,{})
if not cfg: raise SystemExit('Persistent config missing')
if a.mode=='llama':
    models=cfg.setdefault('models',{})
    models['liquid-social']={'url':'http://127.0.0.1:8084/v1','api_key':'local-llama-cpp','vllm_model_name':'agentopia-social','context_length':16384,'max_tokens':256}
    models['liquid-citizen']={'url':'http://127.0.0.1:8081/v1','api_key':'local-llama-cpp','vllm_model_name':'agentopia-citizen','context_length':16384,'max_tokens':512}
    models['liquid-strategy']={'url':'http://127.0.0.1:8082/v1','api_key':'local-llama-cpp','vllm_model_name':'agentopia-strategy','context_length':16384,'max_tokens':768}
    models['cyber-specialist']={'url':'http://127.0.0.1:8083/v1','api_key':'local-llama-cpp','vllm_model_name':'agentopia-cyber','context_length':16384,'max_tokens':768}
    cfg['temperature']=0.1
    cfg['max_concurrency']=64
    cfg.setdefault('world',{}).setdefault('time',{})['n_contact_slot']=4
    cfg['role_model']=['liquid-citizen','liquid-strategy']
    cfg['god_model']='liquid-strategy'; cfg['fallback_model']='liquid-citizen'
    rv=cfg.setdefault('response_validation',{})
    if isinstance(rv,dict): rv['judge_model']='liquid-strategy'
else:
    fb=read(FALLBACK,{})
    if not fb: raise SystemExit('Ollama fallback config is not available')
    old=fb.get('models')
    if isinstance(old,dict): cfg.setdefault('models',{}).update(old)
    for k in ('role_model','god_model','fallback_model'):
        if fb.get(k) is not None: cfg[k]=fb[k]
    if isinstance(fb.get('response_validation'),dict): cfg['response_validation']=fb['response_validation']
write(CFG,cfg); print(a.mode)
