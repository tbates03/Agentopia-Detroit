#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
WORLD=ROOT/'data'/'detroit_persistent'
VERSION='1.4.4.1'
CYBER_WORDS=(
    'cyber','security','nids','hids','siem','endpoint','malware','ransomware','phishing',
    'deepfake','identity','zero-day','vulnerability','exploit','incident response','forensic',
    'firewall','segmentation','ot ','operational technology','threat','attack surface','red team',
    'blue team','purple team','credential','patch posture','telemetry'
)
def read_json(p:Path,d:Any):
    try:return json.loads(p.read_text(encoding='utf-8')) if p.exists() else d
    except Exception:return d
def faction_map():
    raw=read_json(WORLD/'factions.json',{})
    out={}
    fs=raw.get('factions',{}) if isinstance(raw,dict) else {}
    if isinstance(fs,dict):
        for fid,rec in fs.items():
            if not isinstance(rec,dict):continue
            leader=str(rec.get('leader') or '')
            for n in rec.get('members') or []: out[str(n)]=(str(fid),leader)
    return out
def text_of(inputs)->str:
    chunks=[]
    if isinstance(inputs,list):
        for m in inputs:
            if isinstance(m,dict): chunks.append(str(m.get('content') or ''))
    return '\n'.join(chunks).lower()[-12000:]
def choose(agent,inputs)->str|None:
    t=agent.clock.get_time()
    stage=getattr(getattr(t,'stage',None),'name',str(getattr(t,'stage',''))).upper()
    fmap=faction_map(); fac=fmap.get(agent.name); leader=fac[1] if fac else ''
    txt=text_of(inputs)
    if agent.name in {'TGOT','Morbeious'} or (leader and agent.name==leader):
        return 'liquid-strategy'
    if stage in {'CONTACT','AFTER_CONTACT','BEFORE_CONTACT'}:
        return 'liquid-citizen' if fac else 'liquid-social'
    if stage=='PLAN':
        return 'liquid-citizen' if fac else 'liquid-social'
    if stage=='ACTIVITY' and fac and any(k in txt for k in CYBER_WORDS):
        return 'cyber-specialist' if (ROOT/'runtime'/'llama'/'cyber_available').exists() else 'liquid-strategy' if (ROOT/'runtime'/'llama'/'cyber_available').exists() else 'liquid-strategy' if (ROOT/'runtime'/'llama'/'cyber_available').exists() else 'liquid-strategy'
    if stage=='ACTIVITY':
        return 'liquid-citizen'
    return None

def apply_runtime_patches()->None:
    from src.agents.role_agent import RoleAgent
    original=RoleAgent._generate_with_functions
    if getattr(original,'_agentopia_liquid_v144',False): return
    def liquid_generate(self,inputs,*args,**kwargs):
        if kwargs.get('model_override') is None:
            try:
                model=choose(self,inputs)
            except Exception:
                model=None
            if model:
                kwargs['model_override']=model
        return original(self,inputs,*args,**kwargs)
    liquid_generate._agentopia_liquid_v144=True
    RoleAgent._generate_with_functions=liquid_generate

def status():
    fm=faction_map()
    print('Agentopia Detroit Liquid Native v'+VERSION)
    print('Faction-routed citizens:',len(fm))
    print('Routine neutral social lane: liquid-social / 350M QAD')
    print('Routine faction lane: liquid-citizen / 1.2B QAD')
    print('Leaders: liquid-strategy / 2.6B QAD')
    print('Cyber model: activity-only escalation')
if __name__=='__main__': status()
