#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / 'data' / 'detroit_persistent'
HEALTH = WORLD / 'healthcare'
STATE_PATH = HEALTH / 'state.json'
SUMMARY_PATH = HEALTH / 'summary.json'
EVENTS_PATH = HEALTH / 'events.jsonl'
PROVIDERS_PATH = HEALTH / 'providers.json'
CLAIMS_PATH = HEALTH / 'claims.jsonl'
VERSION = '1.7.3'

HUMANITY_PEOPLE = WORLD / 'humanity' / 'people.json'
HUMAN_STATE = WORLD / 'human_economy' / 'state.json'
HUMAN_HOUSEHOLDS = WORLD / 'human_economy' / 'households.json'
CAREER_STATE = WORLD / 'career' / 'state.json'
EDUCATION_STATE = WORLD / 'education' / 'state.json'
BUSINESS_STATE = WORLD / 'business_economy' / 'state.json'

# Fictional 2045 simulation parameters. This model creates synthetic health states
# for fictional Agentopia citizens. It is not a clinical model, diagnosis engine,
# actuarial forecast, or substitute for real medical care.
POLICY = {
    'max_weekly_event_probability': 0.34,
    'medical_debt_payment_cap': 25,
    'medical_debt_cash_reserve': 225,
    'preventive_interval_weeks': 26,
    'preventive_due_probability': 0.42,
    'public_coverage': 0.90,
    'employer_coverage': 0.80,
    'market_coverage': 0.70,
    'basic_coverage': 0.55,
    'senior_coverage': 0.92,
    'patient_min_copay': 5,
}

PROVIDERS = [
    {'id':'riverfront_health','name':'Riverfront Health Services','type':'hospital_system','specialties':['emergency','general','inpatient'],'weekly_capacity':42,'entity_type':'nonprofit'},
    {'id':'detroit_community_care','name':'Detroit Community Care Network','type':'primary_care','specialties':['preventive','general','chronic'],'weekly_capacity':52,'entity_type':'nonprofit'},
    {'id':'motor_city_mental_wellness','name':'Motor City Mental Wellness','type':'behavioral_health','specialties':['mental_health','stress','counseling'],'weekly_capacity':28,'entity_type':'nonprofit'},
    {'id':'great_lakes_specialty','name':'Great Lakes Specialty Center','type':'specialty_care','specialties':['chronic','orthopedic','neurology','cardio'],'weekly_capacity':30,'entity_type':'private'},
    {'id':'detroit_emergency_network','name':'Detroit Emergency Network','type':'emergency_care','specialties':['emergency','trauma'],'weekly_capacity':22,'entity_type':'nonprofit'},
]
PROVIDER_BY_ID = {p['id']:p for p in PROVIDERS}

EVENT_TYPES = {
    'preventive_visit': {'label':'Preventive visit','base_cost':55,'severity':1,'physical_delta':1,'mental_delta':1,'stress_delta':-2,'sick_days':0.0,'care':'preventive'},
    'minor_illness': {'label':'Minor illness','base_cost':75,'severity':1,'physical_delta':-4,'mental_delta':-1,'stress_delta':2,'sick_days':0.5,'care':'general'},
    'injury': {'label':'Injury','base_cost':135,'severity':2,'physical_delta':-8,'mental_delta':-2,'stress_delta':5,'sick_days':1.5,'care':'orthopedic'},
    'mental_health_strain': {'label':'Mental health strain','base_cost':95,'severity':2,'physical_delta':-1,'mental_delta':-8,'stress_delta':10,'sick_days':0.5,'care':'mental_health'},
    'chronic_flare': {'label':'Chronic-condition flare','base_cost':150,'severity':2,'physical_delta':-7,'mental_delta':-2,'stress_delta':5,'sick_days':1.0,'care':'chronic'},
    'acute_episode': {'label':'Acute medical episode','base_cost':300,'severity':3,'physical_delta':-15,'mental_delta':-4,'stress_delta':9,'sick_days':2.5,'care':'emergency'},
    'hospitalization': {'label':'Hospitalization','base_cost':720,'severity':5,'physical_delta':-25,'mental_delta':-8,'stress_delta':15,'sick_days':5.0,'care':'inpatient'},
}

CHRONIC_POOL = [
    ('hypertension','cardio'),('asthma','general'),('arthritis','orthopedic'),
    ('migraine disorder','neurology'),('type 2 diabetes','chronic'),('chronic back pain','orthopedic')
]

PHYSICAL_RISK_SECTORS = {
    'Engineering & Manufacturing','Mobility, Robotics & Infrastructure',
    'Construction & Skilled Trades','Community, Hospitality & Everyday Economy',
    'Law, Government & Public Safety'
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    except Exception:
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t=path.with_suffix(path.suffix+'.tmp')
    t.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    t.replace(path)


def append_jsonl(path: Path, row: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:
        f.write(json.dumps(row,ensure_ascii=False)+'\n')


def tail_jsonl(path: Path, n:int=50) -> list[dict[str,Any]]:
    if not path.exists():return []
    try:lines=path.read_text(encoding='utf-8',errors='ignore').splitlines()[-n:]
    except Exception:return []
    out=[]
    for line in lines:
        try:
            row=json.loads(line)
            if isinstance(row,dict):out.append(row)
        except Exception:pass
    return out


def stable_rng(*parts:Any)->random.Random:
    raw='|'.join(map(str,parts)).encode()
    return random.Random(int(hashlib.sha256(raw).hexdigest()[:16],16))


def current_year_week()->tuple[int,int]:
    cp=read_json(WORLD/'checkpoint.json',{})
    text=str(cp.get('current_time') or cp.get('time') or '')
    m=re.search(r'Y(\d+)-W(\d+)',text)
    return (int(m.group(1)),int(m.group(2))) if m else (2045,1)


def week_key(year:int,week:int)->str:
    return f'Y{year}-W{week:02d}'


def read_profile(name:str)->dict[str,Any]:
    pdir=WORLD/'persona'/name/'profile'
    if not pdir.exists():return {}
    files=sorted(pdir.glob('year=*.json'),key=lambda p:p.name)
    return read_json(files[-1],{}) if files else {}


def humanity_record(name:str)->dict[str,Any]:
    raw=read_json(HUMANITY_PEOPLE,{})
    if not isinstance(raw,dict):return {}
    for rec in raw.values():
        if isinstance(rec,dict) and str(rec.get('name'))==name:return rec
    return {}


def age_for(name:str,profile:dict[str,Any],year:int)->int:
    hr=humanity_record(name)
    try:
        if hr.get('age') is not None:return max(0,int(hr['age']))
    except Exception:pass
    try:return max(0,year-int(profile.get('birth_year')))
    except Exception:return 30


def career_record(name:str)->dict[str,Any]:
    d=read_json(CAREER_STATE,{})
    return (d.get('citizens') or {}).get(name,{}) if isinstance(d,dict) else {}


def education_record(name:str)->dict[str,Any]:
    d=read_json(EDUCATION_STATE,{})
    return (d.get('citizens') or {}).get(name,{}) if isinstance(d,dict) else {}


def household_record(name:str)->tuple[str,dict[str,Any]]:
    d=read_json(HUMAN_STATE,{})
    rows=(d.get('households') or {}) if isinstance(d,dict) else {}
    if not rows:
        h=read_json(HUMAN_HOUSEHOLDS,{})
        rows=h.get('households',h) if isinstance(h,dict) else {}
    if isinstance(rows,dict):
        for hid,rec in rows.items():
            if isinstance(rec,dict) and name in [str(x) for x in rec.get('members',[])]:return str(hid),rec
    return '',{}


def baseline_health(profile:dict[str,Any],name:str)->float:
    try:
        v=float((((profile.get('talents') or {}).get('quantitative') or {}).get('health')))
        if math.isfinite(v):return max(35.0,min(98.0,v))
    except Exception:pass
    return float(stable_rng(name,'baseline-health').randint(62,90))


def insurance_for(name:str,age:int,career:dict[str,Any],hardship:int)->dict[str,Any]:
    status=str(career.get('status') or 'unknown')
    income=int(career.get('weekly_income',0) or 0)
    if age>=65:
        return {'plan':'Great Lakes SeniorCare','type':'public_senior','coverage':POLICY['senior_coverage'],'premium_source':'Human Economy insurance budget'}
    if hardship>=70 or (status=='unemployed' and income<=0):
        return {'plan':'Detroit Care Access','type':'public_assistance','coverage':POLICY['public_coverage'],'premium_source':'Human Economy + public support'}
    if status=='employed':
        return {'plan':'Employer Standard Health','type':'employer','coverage':POLICY['employer_coverage'],'premium_source':'Human Economy insurance budget'}
    if status=='self_employed':
        return {'plan':'Independent Market Health','type':'market','coverage':POLICY['market_coverage'],'premium_source':'Human Economy insurance budget'}
    # A small, deterministic coverage gap exists to make access and debt real,
    # but it never depends on race, gender, religion, ethnicity, or other protected traits.
    if stable_rng(name,'coverage-gap').random()<0.10:
        return {'plan':'Uninsured','type':'uninsured','coverage':0.0,'premium_source':'none'}
    return {'plan':'Detroit Basic Health','type':'basic','coverage':POLICY['basic_coverage'],'premium_source':'Human Economy insurance budget'}


def seed_record(name:str,profile:dict[str,Any],year:int)->dict[str,Any]:
    age=age_for(name,profile,year);base=baseline_health(profile,name)
    _,hh=household_record(name);hardship=int(hh.get('hardship_score',0) or 0)
    career=career_record(name)
    rng=stable_rng(name,'health-seed')
    stress=max(8,min(85,int(rng.randint(18,42)+hardship*0.28+(12 if career.get('status')=='unemployed' else 0))))
    mental=max(40,min(96,int(rng.randint(62,90)-stress*0.18)))
    sleep=max(42,min(96,int(rng.randint(65,88)-stress*0.12)))
    fitness=max(30,min(95,int(base+rng.randint(-14,8))))
    nutrition=max(35,min(95,int(rng.randint(55,88)-hardship*0.10)))
    return {
        'name':name,'age':age,'physical_health':round(base,1),'mental_wellbeing':mental,
        'stress':stress,'sleep_quality':sleep,'fitness':fitness,'nutrition':nutrition,
        'insurance':insurance_for(name,age,career,hardship),'chronic_conditions':[],
        'active_conditions':[],'medical_debt':0,'lifetime_patient_spending':0,
        'lifetime_insurance_claims':0,'lifetime_care_visits':0,'weeks_since_preventive':rng.randint(0,30),
        'sick_days_last_week':0.0,'work_capacity':100,'last_care_provider':None,
        'last_event':'seeded','last_processed_week':None,
    }


def ensure_provider_businesses()->None:
    try:
        import detroit_business_economy as bus
        state=bus.read_json(bus.STATE_PATH,{'version':'1.7.1','businesses':{},'last_processed_week':None,'cumulative':{}})
        if not isinstance(state,dict):return
        businesses=state.setdefault('businesses',{})
        for p in PROVIDERS:
            bid=bus.business_id(p['name'])
            if bid not in businesses:
                businesses[bid]=bus.default_business(p['name'],'Medicine & Health',p['entity_type'],anchor_category='healthcare',payroll=0)
            businesses[bid]['healthcare_provider']=True
            businesses[bid]['provider_id']=p['id']
            businesses[bid]['clinical_capacity_week']=int(p['weekly_capacity'])
        bus.write_json(bus.STATE_PATH,state)
        try:bus.build_summary(state)
        except Exception:pass
    except Exception:
        pass


def finance_runtime(world:Any):
    try:
        import detroit_financial_system as fin
        accounts=fin._accounts();fstate=fin._state();fin._ensure_base_accounts(accounts)
        return fin,accounts,fstate
    except Exception:return None,{},{}


def citizen_account(fin:Any,accounts:dict[str,Any],name:str)->str|None:
    if fin is None:return None
    prof=read_profile(name);dep=0
    try:dep=int((prof.get('init_assets') or {}).get('deposit',0))
    except Exception:pass
    try:return fin._ensure_citizen_account(accounts,name,dep)
    except Exception:return None


def provider_account(provider:dict[str,Any],accounts:dict[str,Any])->str:
    try:
        import detroit_business_economy as bus
        state=bus.read_json(bus.STATE_PATH,{'businesses':{}})
        bid=bus.business_id(provider['name'])
        b=(state.get('businesses') or {}).get(bid)
        if isinstance(b,dict):return bus.business_account(accounts,b)
    except Exception:pass
    return 'institution:glcb:health_billing'


def transfer(fin:Any,accounts:dict[str,Any],fstate:dict[str,Any],src:str,dst:str,amount:int,key:str,time_text:str,tx_type:str,desc:str,meta:dict[str,Any]|None=None)->int:
    if fin is None or not src or not dst:return 0
    try:return int(fin._transfer(accounts,fstate,src,dst,max(0,int(amount)),key,time_text,tx_type,desc,meta or {}))
    except Exception:return 0


def economic_class_for(name:str)->str:
    _,hh=household_record(name)
    return str(hh.get('economic_class') or 'unknown')


def event_probability(rec:dict[str,Any],age:int,hardship:int,career:dict[str,Any])->float:
    physical=float(rec.get('physical_health',70) or 70);stress=float(rec.get('stress',30) or 30)
    p=0.045
    if age>=65:p+=0.075
    elif age>=50:p+=0.045
    elif age>=35:p+=0.020
    elif age<12:p+=0.018
    p+=max(0.0,70-physical)/420.0
    p+=max(0.0,stress-45)/520.0
    p+=max(0.0,hardship-50)/900.0
    if str(career.get('sector') or '') in PHYSICAL_RISK_SECTORS:p+=0.025
    if career.get('status')=='unemployed':p+=0.010
    return max(0.025,min(POLICY['max_weekly_event_probability'],p))


def choose_event(name:str,rec:dict[str,Any],career:dict[str,Any],year:int,week:int)->str:
    rng=stable_rng(name,year,week,'health-event-type')
    chronic=bool(rec.get('chronic_conditions'))
    physical_risk=str(career.get('sector') or '') in PHYSICAL_RISK_SECTORS
    weights=[('minor_illness',42),('mental_health_strain',18),('injury',18 if physical_risk else 10),('acute_episode',5)]
    if chronic:weights.append(('chronic_flare',16))
    else:weights.append(('chronic_flare',3))
    if float(rec.get('physical_health',70))<48:weights.append(('hospitalization',4))
    total=sum(w for _,w in weights);x=rng.uniform(0,total);c=0.0
    for k,w in weights:
        c+=w
        if x<=c:return k
    return 'minor_illness'


def maybe_chronic_onset(name:str,rec:dict[str,Any],age:int,year:int,week:int)->str|None:
    if age<30 or len(rec.get('chronic_conditions') or [])>=3:return None
    annual=0.012+(0.018 if age>=50 else 0)+(0.020 if float(rec.get('physical_health',70))<60 else 0)
    if stable_rng(name,year,week,'chronic-onset').random()>=annual/52.0:return None
    existing=set(map(str,rec.get('chronic_conditions') or []))
    choices=[x for x in CHRONIC_POOL if x[0] not in existing]
    if not choices:return None
    return stable_rng(name,year,week,'chronic-choice').choice(choices)[0]


def provider_for(care:str,usage:Counter)->dict[str,Any]:
    if care=='mental_health':cands=[PROVIDER_BY_ID['motor_city_mental_wellness']]
    elif care in {'emergency','inpatient'}:cands=[PROVIDER_BY_ID['detroit_emergency_network'],PROVIDER_BY_ID['riverfront_health']]
    elif care in {'orthopedic','neurology','cardio','chronic'}:cands=[PROVIDER_BY_ID['great_lakes_specialty'],PROVIDER_BY_ID['riverfront_health']]
    elif care=='preventive':cands=[PROVIDER_BY_ID['detroit_community_care'],PROVIDER_BY_ID['riverfront_health']]
    else:cands=[PROVIDER_BY_ID['detroit_community_care'],PROVIDER_BY_ID['riverfront_health']]
    return min(cands,key=lambda p:usage[p['id']]/max(1,int(p['weekly_capacity'])))


def condition_duration(event_type:str,severity:int)->int:
    if event_type=='hospitalization':return max(2,severity)
    if event_type=='acute_episode':return max(1,severity-1)
    if event_type in {'injury','chronic_flare'}:return max(1,severity)
    if event_type=='mental_health_strain':return max(1,min(4,severity))
    return 1


def recover_existing(rec:dict[str,Any])->None:
    active=[];severe=0
    for c in rec.get('active_conditions') or []:
        if not isinstance(c,dict):continue
        c=dict(c);c['weeks_remaining']=max(0,int(c.get('weeks_remaining',1))-1)
        if c['weeks_remaining']>0:
            active.append(c);severe=max(severe,int(c.get('severity',1)))
    rec['active_conditions']=active
    recovery=2.2 if severe==0 else 0.9
    rec['physical_health']=round(max(20.0,min(100.0,float(rec.get('physical_health',70))+recovery)),1)
    rec['mental_wellbeing']=round(max(20.0,min(100.0,float(rec.get('mental_wellbeing',70))+(1.3 if severe==0 else 0.3))),1)
    rec['stress']=round(max(0.0,min(100.0,float(rec.get('stress',30))-(2.5 if severe==0 else 0.8))),1)


def care_cost(event_type:str,severity:int,name:str,year:int,week:int)->int:
    base=int(EVENT_TYPES[event_type]['base_cost'])
    mult=1.0+0.28*max(0,severity-1)
    jitter=stable_rng(name,year,week,event_type,'cost').uniform(0.88,1.14)
    return max(15,int(round(base*mult*jitter)))


def apply_event(name:str,rec:dict[str,Any],event_type:str,year:int,week:int,key:str,time_text:str,usage:Counter,finctx)->dict[str,Any]:
    spec=EVENT_TYPES[event_type];rng=stable_rng(name,year,week,event_type,'severity')
    severity=int(spec['severity'])
    if event_type in {'injury','mental_health_strain','chronic_flare','acute_episode'}:severity=max(1,min(5,severity+rng.choice([-1,0,0,0,1])))
    if event_type=='minor_illness':severity=1 if rng.random()<0.82 else 2
    care=str(spec['care']);provider=provider_for(care,usage)
    capacity=int(provider['weekly_capacity']);delayed=usage[provider['id']]>=capacity and care not in {'emergency','inpatient'}
    if delayed:
        rec['stress']=min(100,round(float(rec.get('stress',30))+3,1))
        append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'care_delayed','citizen':name,'need':event_type,'provider':provider['name'],'reason':'weekly capacity reached'})
        return {'event_type':event_type,'provider':provider['name'],'delayed':True,'gross_cost':0,'patient_paid':0,'insurance_paid':0,'medical_debt_added':0,'sick_days':0.0}
    usage[provider['id']]+=1
    gross=care_cost(event_type,severity,name,year,week)
    fin,accounts,fstate=finctx
    coverage=float((rec.get('insurance') or {}).get('coverage',0.0) or 0.0)
    insurer_target=max(0,int(round(gross*coverage)))
    patient_target=max(POLICY['patient_min_copay'] if coverage>0 else 0,gross-insurer_target)
    patient_target=min(gross,patient_target);insurer_target=max(0,gross-patient_target)
    dst=provider_account(provider,accounts) if fin is not None else ''
    insurer_paid=transfer(fin,accounts,fstate,'institution:insurance:claims_reserve',dst,insurer_target,key,time_text,'health_insurance_claim','Synthetic healthcare insurance claim',{'citizen':name,'provider':provider['name'],'event_type':event_type,'healthcare_version':VERSION}) if insurer_target else 0
    aid=citizen_account(fin,accounts,name) if fin is not None else None
    patient_paid=transfer(fin,accounts,fstate,aid,dst,patient_target,key,time_text,'healthcare_patient_payment','Healthcare copay/deductible/patient responsibility',{'citizen':name,'provider':provider['name'],'event_type':event_type,'healthcare_version':VERSION}) if aid and patient_target else 0
    debt=max(0,patient_target-patient_paid)
    rec['medical_debt']=int(rec.get('medical_debt',0))+debt
    rec['lifetime_patient_spending']=int(rec.get('lifetime_patient_spending',0))+patient_paid
    rec['lifetime_insurance_claims']=int(rec.get('lifetime_insurance_claims',0))+insurer_paid
    rec['lifetime_care_visits']=int(rec.get('lifetime_care_visits',0))+1
    rec['last_care_provider']=provider['name'];rec['last_event']=event_type
    pd=float(spec['physical_delta']);md=float(spec['mental_delta']);sd=float(spec['stress_delta'])
    scale=1.0+0.18*max(0,severity-int(spec['severity']))
    rec['physical_health']=round(max(10,min(100,float(rec.get('physical_health',70))+pd*scale)),1)
    rec['mental_wellbeing']=round(max(10,min(100,float(rec.get('mental_wellbeing',70))+md*scale)),1)
    rec['stress']=round(max(0,min(100,float(rec.get('stress',30))+sd*scale)),1)
    sick=round(float(spec['sick_days'])*scale,1);rec['sick_days_last_week']=round(float(rec.get('sick_days_last_week',0))+sick,1)
    if event_type!='preventive_visit':
        rec.setdefault('active_conditions',[]).append({'name':spec['label'],'event_type':event_type,'severity':severity,'weeks_remaining':condition_duration(event_type,severity),'provider':provider['name'],'started_week':key})
    else:
        rec['weeks_since_preventive']=0
    append_jsonl(CLAIMS_PATH,{'time':utc_now(),'world_week':key,'citizen':name,'provider':provider['name'],'event_type':event_type,'severity':severity,'gross_cost':gross,'patient_paid':patient_paid,'insurance_paid':insurer_paid,'medical_debt_added':debt,'insurance_plan':(rec.get('insurance') or {}).get('plan')})
    append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'healthcare_visit','citizen':name,'event_type':event_type,'provider':provider['name'],'severity':severity,'gross_cost':gross,'patient_paid':patient_paid,'insurance_paid':insurer_paid,'medical_debt_added':debt})
    return {'event_type':event_type,'provider':provider['name'],'delayed':False,'gross_cost':gross,'patient_paid':patient_paid,'insurance_paid':insurer_paid,'medical_debt_added':debt,'sick_days':sick}


def service_medical_debt(name:str,rec:dict[str,Any],key:str,time_text:str,finctx)->int:
    debt=int(rec.get('medical_debt',0) or 0)
    if debt<=0:return 0
    fin,accounts,fstate=finctx
    aid=citizen_account(fin,accounts,name) if fin is not None else None
    if not aid:return 0
    bal=int(accounts.get(aid,{}).get('balance',0) or 0)
    available=max(0,bal-POLICY['medical_debt_cash_reserve'])
    due=min(debt,POLICY['medical_debt_payment_cap'],available)
    if due<=0:return 0
    paid=transfer(fin,accounts,fstate,aid,'institution:glcb:health_billing',due,key,time_text,'medical_debt_payment','Healthcare payment-plan installment',{'citizen':name,'healthcare_version':VERSION})
    rec['medical_debt']=max(0,debt-paid);rec['lifetime_patient_spending']=int(rec.get('lifetime_patient_spending',0))+paid
    if paid:append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'medical_debt_payment','citizen':name,'amount':paid,'remaining':rec['medical_debt']})
    return paid


def update_wellbeing_context(name:str,rec:dict[str,Any],hardship:int,career:dict[str,Any],edu:dict[str,Any],year:int,week:int)->None:
    rng=stable_rng(name,year,week,'wellbeing')
    stress=float(rec.get('stress',30))
    stress+=max(0,hardship-40)*0.045
    if career.get('status')=='unemployed':stress+=2.5
    if isinstance(edu.get('active_enrollment'),dict):stress+=1.0
    stress+=rng.uniform(-2.0,1.8)
    rec['stress']=round(max(0,min(100,stress)),1)
    rec['sleep_quality']=round(max(25,min(98,74-(rec['stress']-30)*0.32+rng.uniform(-4,4))),1)
    rec['nutrition']=round(max(25,min(98,float(rec.get('nutrition',70))-max(0,hardship-55)*0.025+rng.uniform(-1.2,1.2))),1)
    rec['fitness']=round(max(20,min(100,float(rec.get('fitness',65))+rng.uniform(-1.0,1.0))),1)


def work_capacity(rec:dict[str,Any])->int:
    physical=float(rec.get('physical_health',70));mental=float(rec.get('mental_wellbeing',70));stress=float(rec.get('stress',30));sick=float(rec.get('sick_days_last_week',0))
    severe=max([int(x.get('severity',0)) for x in rec.get('active_conditions',[]) if isinstance(x,dict)] or [0])
    score=100-(100-physical)*0.34-(100-mental)*0.20-max(0,stress-60)*0.20-sick*5-severe*3
    return max(25,min(100,int(round(score))))


def sync_provider_demand(usage:Counter,provider_revenue:Counter)->None:
    try:
        import detroit_business_economy as bus
        state=bus.read_json(bus.STATE_PATH,{'businesses':{}});businesses=state.get('businesses') or {}
        for p in PROVIDERS:
            bid=bus.business_id(p['name']);b=businesses.get(bid)
            if not isinstance(b,dict):continue
            u=int(usage[p['id']]);cap=max(1,int(p['weekly_capacity']))
            b['healthcare_visits_week']=u;b['healthcare_claim_revenue_week']=int(provider_revenue[p['id']])
            b['demand_index']=round(max(0.75,min(1.45,0.85+(u/cap)*0.50)),3)
        bus.write_json(bus.STATE_PATH,state)
        try:bus.build_summary(state)
        except Exception:pass
    except Exception:pass


def build_summary(state:dict[str,Any]|None=None)->dict[str,Any]:
    state=state or read_json(STATE_PATH,{'citizens':{}});citizens=[r for r in (state.get('citizens') or {}).values() if isinstance(r,dict)]
    insured=[r for r in citizens if str((r.get('insurance') or {}).get('type'))!='uninsured']
    active=sum(len(r.get('active_conditions') or []) for r in citizens);chronic=sum(len(r.get('chronic_conditions') or []) for r in citizens)
    claims=tail_jsonl(CLAIMS_PATH,300);week=state.get('last_processed_week');week_claims=[c for c in claims if c.get('world_week')==week]
    usage=Counter();revenue=Counter()
    for c in week_claims:
        pname=str(c.get('provider') or '')
        p=next((x for x in PROVIDERS if x['name']==pname),None)
        if p:usage[p['id']]+=1;revenue[p['id']]+=int(c.get('patient_paid',0))+int(c.get('insurance_paid',0))
    providers=[]
    for p in PROVIDERS:
        u=int(usage[p['id']]);cap=int(p['weekly_capacity'])
        providers.append({**p,'visits_week':u,'utilization_pct':round(100*u/max(1,cap),1),'revenue_week':int(revenue[p['id']])})
    byclass=defaultdict(lambda:{'citizens':0,'physical':0.0,'mental':0.0,'stress':0.0,'medical_debt':0})
    burdens=[]
    for r in citizens:
        cls=economic_class_for(str(r.get('name')));x=byclass[cls];x['citizens']+=1;x['physical']+=float(r.get('physical_health',0));x['mental']+=float(r.get('mental_wellbeing',0));x['stress']+=float(r.get('stress',0));x['medical_debt']+=int(r.get('medical_debt',0))
        burden=(100-float(r.get('physical_health',70)))+(100-float(r.get('mental_wellbeing',70)))+float(r.get('stress',30))+len(r.get('active_conditions') or [])*12+int(r.get('medical_debt',0))/40
        burdens.append({'name':r.get('name'),'physical_health':r.get('physical_health'),'mental_wellbeing':r.get('mental_wellbeing'),'stress':r.get('stress'),'active_conditions':len(r.get('active_conditions') or []),'chronic_conditions':list(r.get('chronic_conditions') or []),'medical_debt':int(r.get('medical_debt',0)),'work_capacity':int(r.get('work_capacity',100)),'burden':round(burden,1)})
    classes=[]
    for k,v in sorted(byclass.items()):
        n=max(1,int(v['citizens']));classes.append({'economic_class':k,'citizens':n,'avg_physical':round(v['physical']/n,1),'avg_mental':round(v['mental']/n,1),'avg_stress':round(v['stress']/n,1),'medical_debt':int(v['medical_debt'])})
    recent=tail_jsonl(EVENTS_PATH,60)
    out={
        'version':VERSION,'updated_at':utc_now(),'world_week':state.get('last_processed_week'),'citizens_tracked':len(citizens),
        'insured':len(insured),'uninsured':len(citizens)-len(insured),'insured_pct':round(100*len(insured)/max(1,len(citizens)),1),
        'average_physical_health':round(mean([float(r.get('physical_health',0)) for r in citizens]),1) if citizens else 0,
        'average_mental_wellbeing':round(mean([float(r.get('mental_wellbeing',0)) for r in citizens]),1) if citizens else 0,
        'average_stress':round(mean([float(r.get('stress',0)) for r in citizens]),1) if citizens else 0,
        'average_sleep_quality':round(mean([float(r.get('sleep_quality',0)) for r in citizens]),1) if citizens else 0,
        'average_work_capacity':round(mean([float(r.get('work_capacity',100)) for r in citizens]),1) if citizens else 0,
        'active_conditions':active,'chronic_conditions':chronic,'medical_debt_total':sum(int(r.get('medical_debt',0)) for r in citizens),
        'healthcare_spending_week':sum(int(c.get('patient_paid',0))+int(c.get('insurance_paid',0)) for c in week_claims),
        'patient_out_of_pocket_week':sum(int(c.get('patient_paid',0)) for c in week_claims),
        'insurance_claims_week':sum(int(c.get('insurance_paid',0)) for c in week_claims),
        'care_visits_week':len(week_claims),'emergency_visits_week':sum(1 for c in week_claims if c.get('event_type') in {'acute_episode','hospitalization'}),
        'preventive_visits_week':sum(1 for c in week_claims if c.get('event_type')=='preventive_visit'),
        'sick_days_week':round(sum(float(r.get('sick_days_last_week',0)) for r in citizens),1),
        'providers':providers,'health_by_economic_class':classes,'highest_health_burden':sorted(burdens,key=lambda x:x['burden'],reverse=True)[:15],
        'recent_events':recent,
        'principles':{
            'synthetic_health_simulation_only':True,'not_medical_advice_or_diagnosis':True,'protected_traits_never_used_for_coverage_or_care':True,
            'baseline_insurance_premiums_live_in_human_economy':True,'acute_claims_use_financial_network':True,'medical_debt_is_persistent_and_noninterest_bearing':True,
            'health_can_influence_choices_but_does_not_automatically_disqualify_careers':True,'existing_citizen_health_is_grandfathered_from_profile_baselines':True,
        }
    }
    write_json(SUMMARY_PATH,out);return out


def initialize()->dict[str,Any]:
    HEALTH.mkdir(parents=True,exist_ok=True);write_json(PROVIDERS_PATH,{'version':VERSION,'providers':PROVIDERS});ensure_provider_businesses()
    year,week=current_year_week();key=week_key(year,week)
    state=read_json(STATE_PATH,{'version':VERSION,'citizens':{},'last_processed_week':None})
    if not isinstance(state,dict):state={'version':VERSION,'citizens':{},'last_processed_week':None}
    state['version']=VERSION;state.setdefault('citizens',{})
    root=WORLD/'persona'
    for pdir in sorted(root.iterdir()) if root.exists() else []:
        if not pdir.is_dir():continue
        name=pdir.name;profile=read_profile(name)
        if not profile:continue
        if name not in state['citizens']:
            state['citizens'][name]=seed_record(name,profile,year)
            append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'health_profile_seeded','citizen':name})
    # Installation never produces claims, medical debt, care events, or health
    # progression for the current simulation week.
    if state.get('last_processed_week') is None:state['last_processed_week']=key
    state['updated_at']=utc_now();write_json(STATE_PATH,state);return build_summary(state)


def process_week(world:Any)->None:
    state=read_json(STATE_PATH,{'version':VERSION,'citizens':{},'last_processed_week':None})
    t=world.clock.get_time();year=int(getattr(t,'year',2045));week=int(getattr(t,'week',1));key=week_key(year,week);time_text=str(t)
    if state.get('last_processed_week')==key:
        build_summary(state);return
    finctx=finance_runtime(world);usage=Counter();provider_revenue=Counter();tot=Counter()
    byname={str(getattr(a,'name','')):a for a in getattr(world,'agents',[])}
    names=set((state.get('citizens') or {}).keys())|set(byname.keys())
    for name in sorted(n for n in names if n):
        profile=read_profile(name)
        if not profile:continue
        rec=(state.setdefault('citizens',{})).get(name)
        if not isinstance(rec,dict):rec=seed_record(name,profile,year);state['citizens'][name]=rec
        rec['age']=age_for(name,profile,year);rec['sick_days_last_week']=0.0;recover_existing(rec)
        career=career_record(name);edu=education_record(name);_,hh=household_record(name);hardship=int(hh.get('hardship_score',0) or 0)
        rec['insurance']=insurance_for(name,int(rec['age']),career,hardship);rec['weeks_since_preventive']=int(rec.get('weeks_since_preventive',0))+1
        update_wellbeing_context(name,rec,hardship,career,edu,year,week)
        service_medical_debt(name,rec,key,time_text,finctx)
        chronic=maybe_chronic_onset(name,rec,int(rec['age']),year,week)
        if chronic:
            rec.setdefault('chronic_conditions',[]).append(chronic);rec['last_event']='chronic_condition_onset';rec['physical_health']=max(20,round(float(rec.get('physical_health',70))-2.5,1))
            append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'chronic_condition_onset','citizen':name,'condition':chronic})
        event_type=None
        due=int(rec.get('weeks_since_preventive',0))>=POLICY['preventive_interval_weeks']
        rng=stable_rng(name,year,week,'health-week')
        if due and rng.random()<POLICY['preventive_due_probability']:
            event_type='preventive_visit'
        elif rng.random()<event_probability(rec,int(rec['age']),hardship,career):
            event_type=choose_event(name,rec,career,year,week)
        if event_type:
            result=apply_event(name,rec,event_type,year,week,key,time_text,usage,finctx)
            if not result.get('delayed'):
                tot['visits']+=1;tot['gross']+=int(result.get('gross_cost',0));tot['patient']+=int(result.get('patient_paid',0));tot['insurance']+=int(result.get('insurance_paid',0));tot['debt']+=int(result.get('medical_debt_added',0));provider=next((p for p in PROVIDERS if p['name']==result.get('provider')),None)
                if provider:provider_revenue[provider['id']]+=int(result.get('patient_paid',0))+int(result.get('insurance_paid',0))
        rec['work_capacity']=work_capacity(rec);rec['last_processed_week']=key
    state['last_processed_week']=key;state['updated_at']=utc_now();write_json(STATE_PATH,state)
    fin,accounts,fstate=finctx
    if fin is not None:
        try:
            fstate['updated_at']=utc_now();fin._save_accounts(accounts);fin._write_json(fin.STATE_PATH,fstate);fin._build_summary(world)
        except Exception:pass
    sync_provider_demand(usage,provider_revenue);build_summary(state)
    append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'healthcare_week_settled','visits':tot['visits'],'gross_cost':tot['gross'],'patient_paid':tot['patient'],'insurance_paid':tot['insurance'],'medical_debt_added':tot['debt']})
    try:world.logger.info('[HEALTH173] Health & Healthcare settled %s: visits=%d patient=$%d insurance=$%d medical_debt_added=$%d',key,tot['visits'],tot['patient'],tot['insurance'],tot['debt'])
    except Exception:pass


def healthcare_context(name:str)->str:
    s=read_json(STATE_PATH,{});r=(s.get('citizens') or {}).get(name,{}) if isinstance(s,dict) else {}
    if not r:return ''
    ins=r.get('insurance') or {};active=r.get('active_conditions') or []
    lines=[
        f'## Agentopia Health & Healthcare Economy v{VERSION}',
        f"- Health snapshot: physical {float(r.get('physical_health',0)):.0f}/100; mental wellbeing {float(r.get('mental_wellbeing',0)):.0f}/100; stress {float(r.get('stress',0)):.0f}/100; sleep quality {float(r.get('sleep_quality',0)):.0f}/100; work capacity {int(r.get('work_capacity',100))}/100.",
        f"- Health coverage: {ins.get('plan','Unknown')} ({int(float(ins.get('coverage',0))*100)}% modeled claim coverage). Baseline premiums/insurance spending are already represented by Human Economy.",
        f"- Medical payment-plan balance: ${int(r.get('medical_debt',0)):,}. Chronic conditions recorded: {', '.join(map(str,r.get('chronic_conditions') or [])) or 'none'}.",
    ]
    if active:lines.append('- Active health issues: '+', '.join(f"{x.get('name')} ({int(x.get('weeks_remaining',0))}w)" for x in active[:4] if isinstance(x,dict))+'.')
    else:lines.append('- Active health issues: none recorded this week.')
    lines.append('- Health should influence normal human choices such as rest, care, spending, stress, work pacing and family decisions, but it does not automatically determine your identity or career eligibility.')
    lines.append('- This is synthetic Agentopia health simulation, not real medical advice or diagnosis.')
    return '\n'.join(lines)


def apply_runtime_patches()->None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.world.world import World
    if not getattr(DataManager.character_prompt,'_agentopia_healthcare_v173',False):
        original=DataManager.character_prompt
        def health_prompt(self):
            base=original(self)
            try:
                ctx=healthcare_context(self.char);return str(base)+(('\n\n'+ctx) if ctx else '')
            except Exception:return base
        health_prompt._agentopia_healthcare_v173=True;DataManager.character_prompt=health_prompt
    # Health settles AFTER Education -> Career -> Human Economy -> Business Economy.
    # This lets economic hardship, insurance context, and employer state influence
    # the new week's health simulation without double-processing the current week.
    if not getattr(World._before_week_start,'_agentopia_healthcare_v173',False):
        original_before=World._before_week_start
        def health_before(self):
            result=original_before(self)
            try:process_week(self)
            except Exception as e:
                try:self.logger.warning('[HEALTH173] healthcare week failed: %s',e)
                except Exception:pass
            return result
        health_before._agentopia_healthcare_v173=True;World._before_week_start=health_before


def status()->None:
    s=initialize();print(f'Agentopia Detroit Health & Healthcare Economy v{VERSION}')
    print('Citizens:',s.get('citizens_tracked'),'Insured:',s.get('insured'),'Uninsured:',s.get('uninsured'),'Coverage:',str(s.get('insured_pct'))+'%')
    print('Physical:',s.get('average_physical_health'),'Mental:',s.get('average_mental_wellbeing'),'Stress:',s.get('average_stress'),'Work capacity:',s.get('average_work_capacity'))
    print('Active conditions:',s.get('active_conditions'),'Chronic:',s.get('chronic_conditions'),'Medical debt:',s.get('medical_debt_total'))
    print('Care visits this week:',s.get('care_visits_week'),'Claims:',s.get('insurance_claims_week'),'Patient out-of-pocket:',s.get('patient_out_of_pocket_week'))
    print('State:',HEALTH)


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['init','status'],nargs='?',default='status');args=ap.parse_args()
    if args.command=='init':initialize()
    status()
