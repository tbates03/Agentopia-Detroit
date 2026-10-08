#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / 'data' / 'detroit_persistent'
EDU = WORLD / 'education'
STATE_PATH = EDU / 'state.json'
INSTITUTIONS_PATH = EDU / 'institutions.json'
PROGRAMS_PATH = EDU / 'programs.json'
SUMMARY_PATH = EDU / 'summary.json'
EVENTS_PATH = EDU / 'events.ndjson'
VERSION = '1.7.2'

CAREER_STATE = WORLD / 'career' / 'state.json'
CAREER_CATALOG = WORLD / 'career' / 'catalog.json'
HUMAN_STATE = WORLD / 'human_economy' / 'state.json'
HUMAN_HOUSEHOLDS = WORLD / 'human_economy' / 'households.json'
HUMANITY_PEOPLE = WORLD / 'humanity' / 'people.json'

EDU_LABELS = {
    0: 'No formal requirement',
    1: 'High school / equivalent',
    2: 'Certificate / trade',
    3: 'Associate / technical degree',
    4: "Bachelor's degree",
    5: 'Graduate / professional degree',
}

POLICY = {
    'weekly_student_loan_interest': 0.0012,
    'cash_floor': 75,
    'repayment_income_share': 0.045,
    'minimum_weekly_repayment': 5,
    'public_k12_support_per_student': 10,
    'low_income_scholarship_rate': 0.60,
    'middle_income_scholarship_rate': 0.25,
    'max_scholarship_rate': 0.80,
    'quarterly_enrollment_cadence_weeks': 13,
}

INSTITUTIONS = [
    {'id':'detroit_public_learning','name':'Detroit Public Learning Network','type':'public_k12','focus':'K-12 foundational learning','bank_id':'dcb'},
    {'id':'detroit_trades_academy','name':'Detroit Technical & Trades Academy','type':'technical','focus':'skilled trades and apprenticeships','bank_id':'mccu'},
    {'id':'motor_city_community_college','name':'Motor City Community College','type':'community_college','focus':'associate degrees and workforce mobility','bank_id':'dcb'},
    {'id':'great_lakes_technology','name':'Great Lakes Institute of Technology','type':'technology','focus':'AI, software, cybersecurity and systems','bank_id':'mccu'},
    {'id':'michigan_central_mobility','name':'Michigan Central Mobility Institute','type':'mobility','focus':'EV, robotics, mobility and infrastructure','bank_id':'dcb'},
    {'id':'detroit_health_sciences','name':'Detroit Health Sciences College','type':'health','focus':'healthcare and clinical professions','bank_id':'glcb'},
    {'id':'detroit_metropolitan_university','name':'Detroit Metropolitan University','type':'university','focus':'broad undergraduate and professional education','bank_id':'dcb'},
    {'id':'motown_arts_media','name':'Motown Arts & Media Conservatory','type':'arts','focus':'creative, media and entertainment','bank_id':'mccu'},
    {'id':'detroit_civic_academy','name':'Detroit Civic & Public Safety Academy','type':'public_service','focus':'government, law and public safety','bank_id':'dcb'},
    {'id':'great_lakes_research','name':'Great Lakes Graduate Research Institute','type':'graduate_research','focus':'advanced research, science and engineering','bank_id':'glcb'},
]

# target_level maps directly to Career Economy's education ladder. Programs that
# do not raise formal education still add credentials and skills.
PROGRAMS = [
    {'id':'k12_core','title':'Detroit K-12 Core','institution':'detroit_public_learning','pathway':'K-12','target_level':1,'duration_weeks':624,'tuition_week':0,'minimum_level':0,'minimum_age':5,'skills':['communication','math','science','digital_literacy','critical_thinking','civic_literacy'],'credential':'High School Diploma','sector':'General'},
    {'id':'adult_equivalency','title':'Adult High School Equivalency','institution':'motor_city_community_college','pathway':'Adult Education','target_level':1,'duration_weeks':26,'tuition_week':18,'minimum_level':0,'minimum_age':18,'skills':['communication','math','digital_literacy','critical_thinking'],'credential':'High School Equivalency','sector':'General'},
    {'id':'electrical_apprenticeship','title':'Electrical Apprenticeship','institution':'detroit_trades_academy','pathway':'Apprenticeship','target_level':2,'duration_weeks':104,'tuition_week':0,'minimum_level':1,'minimum_age':18,'skills':['electrical','troubleshooting','safety','construction'],'credential':'Journeyperson Electrical Certificate','sector':'Construction & Skilled Trades'},
    {'id':'plumbing_hvac_apprenticeship','title':'Plumbing & HVAC Apprenticeship','institution':'detroit_trades_academy','pathway':'Apprenticeship','target_level':2,'duration_weeks':104,'tuition_week':0,'minimum_level':1,'minimum_age':18,'skills':['hvac','plumbing','troubleshooting','safety'],'credential':'Skilled Trades Apprenticeship Certificate','sector':'Construction & Skilled Trades'},
    {'id':'industrial_auto_apprenticeship','title':'Automotive & Industrial Technician Apprenticeship','institution':'detroit_trades_academy','pathway':'Apprenticeship','target_level':2,'duration_weeks':78,'tuition_week':0,'minimum_level':1,'minimum_age':18,'skills':['mechanical','diagnostics','manufacturing','safety'],'credential':'Industrial Technician Certificate','sector':'Engineering & Manufacturing'},
    {'id':'advanced_manufacturing_cert','title':'Advanced Manufacturing Certificate','institution':'detroit_trades_academy','pathway':'Certificate','target_level':2,'duration_weeks':39,'tuition_week':28,'minimum_level':1,'minimum_age':18,'skills':['manufacturing','automation','quality','safety'],'credential':'Advanced Manufacturing Certificate','sector':'Engineering & Manufacturing'},
    {'id':'cybersecurity_cert','title':'Cybersecurity Operations Certificate','institution':'great_lakes_technology','pathway':'Certificate','target_level':2,'duration_weeks':39,'tuition_week':32,'minimum_level':1,'minimum_age':18,'skills':['cybersecurity','analysis','networking','incident_response'],'credential':'Cybersecurity Operations Certificate','sector':'Cybersecurity & Intelligence'},
    {'id':'ai_software_cert','title':'AI & Software Development Certificate','institution':'great_lakes_technology','pathway':'Certificate','target_level':2,'duration_weeks':39,'tuition_week':32,'minimum_level':1,'minimum_age':18,'skills':['programming','systems_thinking','analysis','ai_orchestration'],'credential':'AI & Software Certificate','sector':'AI, Software & Technology'},
    {'id':'health_support_cert','title':'Healthcare Support Certificate','institution':'detroit_health_sciences','pathway':'Certificate','target_level':2,'duration_weeks':39,'tuition_week':30,'minimum_level':1,'minimum_age':18,'skills':['healthcare','science','empathy','organization'],'credential':'Healthcare Support Certificate','sector':'Medicine & Health'},
    {'id':'mobility_ev_cert','title':'EV & Mobility Systems Certificate','institution':'michigan_central_mobility','pathway':'Certificate','target_level':2,'duration_weeks':39,'tuition_week':32,'minimum_level':1,'minimum_age':18,'skills':['engineering','automation','systems_thinking','electrical'],'credential':'EV & Mobility Systems Certificate','sector':'Mobility, Robotics & Infrastructure'},
    {'id':'business_ops_cert','title':'Business Operations Certificate','institution':'motor_city_community_college','pathway':'Certificate','target_level':2,'duration_weeks':26,'tuition_week':24,'minimum_level':1,'minimum_age':18,'skills':['business','planning','communication','analysis'],'credential':'Business Operations Certificate','sector':'Business & Operations'},
    {'id':'culinary_hospitality_cert','title':'Culinary & Hospitality Certificate','institution':'motown_arts_media','pathway':'Certificate','target_level':2,'duration_weeks':26,'tuition_week':24,'minimum_level':1,'minimum_age':18,'skills':['cooking','hospitality','planning','customer_service'],'credential':'Culinary & Hospitality Certificate','sector':'Community, Hospitality & Everyday Economy'},
    {'id':'public_safety_cert','title':'Public Safety Foundations Certificate','institution':'detroit_civic_academy','pathway':'Certificate','target_level':2,'duration_weeks':26,'tuition_week':20,'minimum_level':1,'minimum_age':18,'skills':['public_safety','communication','judgment','emergency_response'],'credential':'Public Safety Foundations Certificate','sector':'Law, Government & Public Safety'},
    {'id':'associate_technology','title':'Associate in Applied Technology','institution':'motor_city_community_college','pathway':'Associate','target_level':3,'duration_weeks':104,'tuition_week':48,'minimum_level':1,'minimum_age':18,'skills':['programming','systems_thinking','analysis','networking'],'credential':'Associate in Applied Technology','sector':'AI, Software & Technology'},
    {'id':'associate_health','title':'Associate in Health Sciences','institution':'motor_city_community_college','pathway':'Associate','target_level':3,'duration_weeks':104,'tuition_week':50,'minimum_level':1,'minimum_age':18,'skills':['healthcare','science','empathy','organization'],'credential':'Associate in Health Sciences','sector':'Medicine & Health'},
    {'id':'associate_business','title':'Associate in Business & Operations','institution':'motor_city_community_college','pathway':'Associate','target_level':3,'duration_weeks':104,'tuition_week':46,'minimum_level':1,'minimum_age':18,'skills':['business','planning','analysis','communication'],'credential':'Associate in Business & Operations','sector':'Business & Operations'},
    {'id':'associate_technical_trades','title':'Associate in Technical Trades','institution':'detroit_trades_academy','pathway':'Associate','target_level':3,'duration_weeks':104,'tuition_week':42,'minimum_level':2,'minimum_age':18,'skills':['engineering','troubleshooting','safety','manufacturing'],'credential':'Associate in Technical Trades','sector':'Construction & Skilled Trades'},
    {'id':'bachelor_computing_ai','title':'Bachelor of Computing & AI','institution':'great_lakes_technology','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':70,'minimum_level':1,'minimum_age':18,'skills':['programming','systems_thinking','analysis','ai_orchestration'],'credential':'Bachelor of Computing & AI','sector':'AI, Software & Technology'},
    {'id':'bachelor_engineering','title':'Bachelor of Engineering','institution':'detroit_metropolitan_university','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':72,'minimum_level':1,'minimum_age':18,'skills':['engineering','math','troubleshooting','safety'],'credential':'Bachelor of Engineering','sector':'Engineering & Manufacturing'},
    {'id':'bachelor_business','title':'Bachelor of Business Administration','institution':'detroit_metropolitan_university','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':66,'minimum_level':1,'minimum_age':18,'skills':['business','leadership','strategy','analysis'],'credential':'Bachelor of Business Administration','sector':'Business & Operations'},
    {'id':'bachelor_health','title':'Bachelor of Health Sciences','institution':'detroit_health_sciences','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':72,'minimum_level':1,'minimum_age':18,'skills':['healthcare','science','research','empathy'],'credential':'Bachelor of Health Sciences','sector':'Medicine & Health'},
    {'id':'bachelor_education','title':'Bachelor of Education','institution':'detroit_metropolitan_university','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':62,'minimum_level':1,'minimum_age':18,'skills':['teaching','communication','planning','research'],'credential':'Bachelor of Education','sector':'Education'},
    {'id':'bachelor_arts_media','title':'Bachelor of Arts & Media','institution':'motown_arts_media','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':60,'minimum_level':1,'minimum_age':18,'skills':['creativity','design','communication','media'],'credential':'Bachelor of Arts & Media','sector':'Creative, Media & Entertainment'},
    {'id':'bachelor_public_policy','title':'Bachelor of Public Policy & Justice','institution':'detroit_civic_academy','pathway':'Bachelor','target_level':4,'duration_weeks':208,'tuition_week':64,'minimum_level':1,'minimum_age':18,'skills':['law','communication','judgment','policy'],'credential':'Bachelor of Public Policy & Justice','sector':'Law, Government & Public Safety'},
    {'id':'master_technology','title':'Master of Advanced Technology','institution':'great_lakes_technology','pathway':'Graduate','target_level':5,'duration_weeks':78,'tuition_week':96,'minimum_level':4,'minimum_age':21,'skills':['programming','systems_thinking','research','ai_orchestration'],'credential':'Master of Advanced Technology','sector':'AI, Software & Technology'},
    {'id':'master_engineering','title':'Master of Engineering Systems','institution':'great_lakes_research','pathway':'Graduate','target_level':5,'duration_weeks':78,'tuition_week':98,'minimum_level':4,'minimum_age':21,'skills':['engineering','research','systems_thinking','automation'],'credential':'Master of Engineering Systems','sector':'Engineering & Manufacturing'},
    {'id':'master_business','title':'Master of Business & Finance','institution':'detroit_metropolitan_university','pathway':'Graduate','target_level':5,'duration_weeks':78,'tuition_week':92,'minimum_level':4,'minimum_age':21,'skills':['business','leadership','strategy','finance'],'credential':'Master of Business & Finance','sector':'Executive & Ownership'},
    {'id':'graduate_education','title':'Graduate Education & Leadership','institution':'detroit_metropolitan_university','pathway':'Graduate','target_level':5,'duration_weeks':78,'tuition_week':82,'minimum_level':4,'minimum_age':21,'skills':['teaching','leadership','research','planning'],'credential':'Graduate Education & Leadership Degree','sector':'Education'},
    {'id':'professional_law','title':'Professional Law Program','institution':'detroit_civic_academy','pathway':'Professional','target_level':5,'duration_weeks':156,'tuition_week':110,'minimum_level':4,'minimum_age':21,'skills':['law','research','communication','judgment'],'credential':'Professional Law Degree','sector':'Law, Government & Public Safety'},
    {'id':'professional_medicine','title':'Professional Medicine Program','institution':'detroit_health_sciences','pathway':'Professional','target_level':5,'duration_weeks':208,'tuition_week':125,'minimum_level':4,'minimum_age':21,'skills':['healthcare','science','research','judgment'],'credential':'Professional Medical Degree','sector':'Medicine & Health'},
    {'id':'doctoral_research','title':'Doctoral Research Program','institution':'great_lakes_research','pathway':'Doctoral','target_level':5,'duration_weeks':208,'tuition_week':90,'minimum_level':4,'minimum_age':21,'skills':['research','analysis','science','writing'],'credential':'Doctoral Research Degree','sector':'Science & Research'},
    {'id':'leadership_entrepreneurship','title':'Leadership & Entrepreneurship Certificate','institution':'detroit_metropolitan_university','pathway':'Professional Certificate','target_level':2,'duration_weeks':26,'tuition_week':35,'minimum_level':1,'minimum_age':18,'skills':['leadership','strategy','business','finance'],'credential':'Leadership & Entrepreneurship Certificate','sector':'Executive & Ownership'},
    {'id':'career_retraining','title':'Career Retraining Accelerator','institution':'motor_city_community_college','pathway':'Retraining','target_level':0,'duration_weeks':26,'tuition_week':22,'minimum_level':1,'minimum_age':18,'skills':['analysis','communication','digital_literacy','planning'],'credential':'Career Retraining Certificate','sector':'General'},
]

PROGRAM_BY_ID = {p['id']: p for p in PROGRAMS}
INSTITUTION_BY_ID = {i['id']: i for i in INSTITUTIONS}

RELATED_SECTORS = {
    'Cybersecurity & Intelligence':['AI, Software & Technology'],
    'Mobility, Robotics & Infrastructure':['Engineering & Manufacturing','AI, Software & Technology'],
    'Construction & Skilled Trades':['Engineering & Manufacturing','Business & Operations'],
    'Science & Research':['Engineering & Manufacturing','Medicine & Health'],
    'Executive & Ownership':['Business & Operations'],
    'Community, Hospitality & Everyday Economy':['Business & Operations','Creative, Media & Entertainment'],
    'Creative, Media & Entertainment':['Business & Operations'],
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
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def append_event(event: str, **payload: Any) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'timestamp': utc_now(), 'event': event, **payload}, ensure_ascii=False) + '\n')


def tail_events(n: int = 50) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        lines = EVENTS_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-n:]
    except Exception:
        return []
    out=[]
    for line in lines:
        try:
            row=json.loads(line)
            if isinstance(row,dict): out.append(row)
        except Exception:
            pass
    return out


def stable_rng(*parts: Any) -> random.Random:
    raw='|'.join(map(str,parts)).encode()
    return random.Random(int(hashlib.sha256(raw).hexdigest()[:16],16))


def current_year_week() -> tuple[int,int]:
    cp=read_json(WORLD/'checkpoint.json',{})
    text=str(cp.get('current_time') or cp.get('time') or '')
    m=re.search(r'Y(\d+)-W(\d+)',text)
    return (int(m.group(1)),int(m.group(2))) if m else (2045,1)


def week_key(year:int,week:int)->str:
    return f'Y{year}-W{week:02d}'


def read_profile(name:str)->dict[str,Any]:
    pdir=WORLD/'persona'/name/'profile'
    if not pdir.exists(): return {}
    files=sorted(pdir.glob('year=*.json'),key=lambda p:p.name)
    if not files:return {}
    return read_json(files[-1],{})


def age_for(name:str, profile:dict[str,Any], year:int)->int:
    humanity=read_json(HUMANITY_PEOPLE,{})
    people=humanity.get('people',humanity) if isinstance(humanity,dict) else {}
    rec=people.get(name,{}) if isinstance(people,dict) else {}
    try:
        if rec.get('age') is not None:return max(0,int(rec['age']))
    except Exception:pass
    try:return max(0,year-int(profile.get('birth_year')))
    except Exception:return 30


def education_from_career(name:str)->tuple[int,str]:
    c=read_json(CAREER_STATE,{})
    r=(c.get('citizens') or {}).get(name,{}) if isinstance(c,dict) else {}
    try:level=int(r.get('education_level',1))
    except Exception:level=1
    return max(0,min(5,level)),str(r.get('education') or EDU_LABELS.get(level,'Unknown'))


def profile_skills(profile:dict[str,Any], career_rec:dict[str,Any]|None=None)->dict[str,float]:
    out:dict[str,float]={}
    raw=profile.get('init_skills') or {}
    if isinstance(raw,dict):
        for k,v in raw.items():
            try:out[str(k)]=max(0.0,min(300.0,float(v)))
            except Exception:pass
    # Career-seeded citizens often have sparse legacy skill dictionaries. Give
    # their established profession a conservative skill floor without inventing
    # mastery in unrelated fields.
    if career_rec:
        catalog=read_json(CAREER_CATALOG,{})
        rows=catalog.get('careers',[]) if isinstance(catalog,dict) else []
        cur=next((x for x in rows if isinstance(x,dict) and x.get('id')==career_rec.get('career_id')),None)
        if cur:
            floor=max(40,min(180,35+int(cur.get('tier',2))*13))
            for tag in cur.get('skill_tags',[]) or []:
                out[str(tag)]=max(out.get(str(tag),0.0),float(floor))
    return out


def seed_record(name:str, profile:dict[str,Any], year:int)->dict[str,Any]:
    career=read_json(CAREER_STATE,{})
    cr=(career.get('citizens') or {}).get(name,{}) if isinstance(career,dict) else {}
    level,label=education_from_career(name)
    age=age_for(name,profile,year)
    if age<18:
        level=0;label='K-12 in progress'
    creds=[]
    if level>=1:creds.append(label)
    out={
        'name':name,'age':age,'education_level':level,'education':label,
        'credentials':creds,'skills':profile_skills(profile,cr),'active_enrollment':None,
        'student_debt':0,'tuition_arrears':0,'education_weeks_since_v172':0,'completed_programs':[],
        'k12_weeks':max(0,(age-6)*52) if 6<=age<18 else 0,'status':'k12' if 5<=age<18 else 'not_enrolled',
        'last_event':'seeded','scholarships_received':0,'tuition_paid':0,'loan_principal_borrowed':0,
    }
    if 5<=age<18:
        p=PROGRAM_BY_ID['k12_core']
        out['active_enrollment']={'program_id':p['id'],'title':p['title'],'institution_id':p['institution'],'weeks_completed':out['k12_weeks'],'weeks_required':p['duration_weeks'],'started_week':'seed','reason':'grandfathered_k12','pathway':'K-12','target_career_id':None}
    return out


def career_context_data(name:str)->tuple[dict[str,Any],list[dict[str,Any]]]:
    state=read_json(CAREER_STATE,{})
    rec=(state.get('citizens') or {}).get(name,{}) if isinstance(state,dict) else {}
    catalog=read_json(CAREER_CATALOG,{})
    rows=[x for x in catalog.get('careers',[]) if isinstance(x,dict)] if isinstance(catalog,dict) else []
    return rec,rows


def household_pressure(name:str)->tuple[str,int,int]:
    hs=read_json(HUMAN_STATE,{})
    rows=(hs.get('households') or {}) if isinstance(hs,dict) else {}
    # v1.7.0 state can also keep household records in households.json.
    if not rows:
        hraw=read_json(HUMAN_HOUSEHOLDS,{})
        rows=hraw.get('households',hraw) if isinstance(hraw,dict) else {}
    if isinstance(rows,dict):
        for hid,h in rows.items():
            if not isinstance(h,dict):continue
            if name in [str(x) for x in h.get('members',[])]:
                return str(hid),int(h.get('hardship_score',0) or 0),int(h.get('ending_cash',0) or 0)
    return '',0,0


def institution_account(accounts:dict[str,dict[str,Any]], institution_id:str)->str:
    inst=INSTITUTION_BY_ID[institution_id]
    aid=f'education:{institution_id}:operating'
    accounts.setdefault(aid,{
        'account_id':aid,'name':f"{inst['name']} Operating",'owner_type':'institution',
        'bank_id':inst.get('bank_id','dcb'),'balance':0,'frozen':0,'status':'open'
    })
    return aid


def finance_context(world:Any):
    try:
        import detroit_financial_system as fin
        accounts=fin._accounts(); finstate=fin._state(); fin._ensure_base_accounts(accounts)
        for inst in INSTITUTIONS:institution_account(accounts,inst['id'])
        return fin,accounts,finstate
    except Exception:
        return None,None,None


def citizen_account(fin:Any, accounts:dict[str,dict[str,Any]], name:str)->str|None:
    if fin is None:return None
    # Keep the existing balance when the finance record already exists. If a
    # newly activated citizen has no account yet, initialize from profile assets.
    prof=read_profile(name)
    dep=0
    try:dep=int((prof.get('init_assets') or {}).get('deposit',0))
    except Exception:pass
    return fin._ensure_citizen_account(accounts,name,dep)


def post_transfer(fin:Any,accounts:dict[str,dict[str,Any]],finstate:dict[str,Any],src:str,dst:str,amount:int,key:str,time_text:str,tx_type:str,desc:str,meta:dict[str,Any]|None=None)->int:
    if fin is None:return 0
    return int(fin._transfer(accounts,finstate,src,dst,max(0,int(amount)),key,time_text,tx_type,desc,meta or {}))


def scholarship_rate(name:str,career_rec:dict[str,Any],hardship:int)->float:
    income=int(career_rec.get('weekly_income',0) or 0)
    if hardship>=70 or income<=325:return POLICY['low_income_scholarship_rate']
    if hardship>=40 or income<=550:return POLICY['middle_income_scholarship_rate']
    # Merit assistance is deterministic and modest.
    perf=int(career_rec.get('performance',60) or 60)
    return 0.15 if perf>=85 else (0.05 if perf>=75 else 0.0)


def skill_gain(program:dict[str,Any])->float:
    p=str(program.get('pathway'))
    if p=='K-12':return 0.28
    if p in {'Certificate','Professional Certificate','Retraining'}:return 0.95
    if p=='Apprenticeship':return 1.10
    if p=='Associate':return 0.72
    if p=='Bachelor':return 0.62
    return 0.68


def program_for_target(rec:dict[str,Any],career_rec:dict[str,Any],catalog:list[dict[str,Any]],age:int)->dict[str,Any]|None:
    level=int(rec.get('education_level',1) or 1)
    aspirations=[str(x) for x in career_rec.get('aspirations',[]) or []]
    target=next((c for cid in aspirations for c in catalog if c.get('id')==cid),None)
    target_level=int(target.get('minimum_education_level',level)) if target else level
    sector=str(target.get('sector') or career_rec.get('sector') or 'General') if target else str(career_rec.get('sector') or 'General')
    if level<target_level:
        candidates=[p for p in PROGRAMS if int(p.get('target_level',0))==level+1 and int(p.get('minimum_level',0))<=level and age>=int(p.get('minimum_age',18))]
        same=[p for p in candidates if p.get('sector')==sector]
        if same:
            candidates=same
        else:
            related=RELATED_SECTORS.get(sector,[])
            related_matches=[p for p in candidates if p.get('sector') in related]
            if related_matches:candidates=related_matches
        if candidates:return sorted(candidates,key=lambda p:(int(p['duration_weeks']),int(p['tuition_week'])))[0]
    # If the aspiration is not blocked by education, use targeted retraining for
    # unemployed or dissatisfied adults rather than automatically stacking degrees.
    if target:
        base=dict(PROGRAM_BY_ID['career_retraining'])
        base['id']='career_retraining:'+str(target.get('id'))
        base['title']='Career Retraining: '+str(target.get('title'))
        base['sector']=sector
        base['skills']=list(target.get('skill_tags') or base['skills'])
        base['target_career_id']=target.get('id')
        return base
    return None


def program_by_runtime_id(pid:str)->dict[str,Any]|None:
    if pid.startswith('career_retraining:'):
        target_id=pid.split(':',1)[1]
        catalog=read_json(CAREER_CATALOG,{})
        target=next((x for x in catalog.get('careers',[]) if isinstance(x,dict) and x.get('id')==target_id),None) if isinstance(catalog,dict) else None
        p=dict(PROGRAM_BY_ID['career_retraining'])
        p['id']=pid
        if target:
            p['title']='Career Retraining: '+str(target.get('title'))
            p['sector']=str(target.get('sector') or 'General')
            p['skills']=list(target.get('skill_tags') or p['skills'])
            p['target_career_id']=target_id
        return p
    return PROGRAM_BY_ID.get(pid)


def enroll(name:str,rec:dict[str,Any],program:dict[str,Any],key:str,reason:str)->None:
    rec['active_enrollment']={
        'program_id':program['id'],'title':program['title'],'institution_id':program['institution'],
        'weeks_completed':0,'weeks_required':int(program['duration_weeks']),
        'started_week':key,'reason':reason,'pathway':program['pathway'],
        'target_career_id':program.get('target_career_id'),
    }
    rec['status']='k12' if program['pathway']=='K-12' else ('apprentice' if program['pathway']=='Apprenticeship' else 'student')
    rec['last_event']='enrolled'
    append_event('enrolled',citizen=name,program=program['title'],institution=INSTITUTION_BY_ID[program['institution']]['name'],reason=reason,world_week=key)


def maybe_enroll(name:str,rec:dict[str,Any],profile:dict[str,Any],career_rec:dict[str,Any],catalog:list[dict[str,Any]],year:int,week:int)->None:
    if rec.get('active_enrollment'):return
    age=int(rec.get('age',age_for(name,profile,year)))
    if 5<=age<18:
        enroll(name,rec,PROGRAM_BY_ID['k12_core'],week_key(year,week),'compulsory_k12')
        return
    if age<18:return
    # Migrate the simple v1.6.1.4 retraining flag into the full v1.7.2 system.
    tr=career_rec.get('training')
    if isinstance(tr,dict) and tr.get('target_career_id'):
        target=next((c for c in catalog if c.get('id')==tr.get('target_career_id')),None)
        if target:
            p=dict(PROGRAM_BY_ID['career_retraining']);p['id']='career_retraining:'+str(target['id']);p['title']='Career Retraining: '+str(target['title']);p['sector']=target.get('sector','General');p['skills']=list(target.get('skill_tags') or p['skills']);p['target_career_id']=target['id']
            enroll(name,rec,p,week_key(year,week),'career_retraining_request');career_rec['training']=None;return
    # Adults reevaluate education on a quarterly cadence, not every week.
    if week % int(POLICY['quarterly_enrollment_cadence_weeks']) != 0:return
    rng=stable_rng(name,year,week,'education-enroll')
    status=str(career_rec.get('status') or '')
    satisfaction=int(career_rec.get('career_satisfaction',60) or 60)
    chance=0.06
    if status=='unemployed':chance=0.32
    elif satisfaction<55:chance=0.18
    elif satisfaction<68:chance=0.11
    if rng.random()>chance:return
    p=program_for_target(rec,career_rec,catalog,age)
    if p:enroll(name,rec,p,week_key(year,week),'career_mobility')


def complete_program(name:str,rec:dict[str,Any],program:dict[str,Any],career_rec:dict[str,Any],key:str)->None:
    old=int(rec.get('education_level',0) or 0)
    target=int(program.get('target_level',0) or 0)
    if target>old:
        rec['education_level']=min(5,target);rec['education']=EDU_LABELS[min(5,target)]
    cred=str(program.get('credential') or program['title'])
    if cred and cred not in rec.setdefault('credentials',[]):rec['credentials'].append(cred)
    if program['id'] not in rec.setdefault('completed_programs',[]):rec['completed_programs'].append(program['id'])
    rec['active_enrollment']=None;rec['status']='not_enrolled';rec['last_event']='completed'
    career_rec['education_level']=int(rec.get('education_level',old));career_rec['education']=str(rec.get('education',EDU_LABELS.get(old,'Unknown')));career_rec['skills']=dict(rec.get('skills') or {});career_rec['credentials']=list(rec.get('credentials') or [])
    append_event('program_completed',citizen=name,program=program['title'],credential=cred,education=rec.get('education'),world_week=key)


def process_k12(name:str,rec:dict[str,Any],program:dict[str,Any],career_rec:dict[str,Any],year:int,key:str,finctx:tuple[Any,Any,Any]|None,time_text:str)->None:
    rec['k12_weeks']=int(rec.get('k12_weeks',0))+1
    gain=skill_gain(program)
    for tag in program['skills']:rec.setdefault('skills',{})[tag]=min(300.0,round(float(rec['skills'].get(tag,20))+gain,2))
    # Fund public education from the municipal treasury when the Financial
    # Network is available. No tuition or debt is assigned to children.
    if finctx and finctx[0]:
        fin,accounts,finstate=finctx;dst=institution_account(accounts,program['institution'])
        post_transfer(fin,accounts,finstate,'institution:dcb:municipal_treasury',dst,POLICY['public_k12_support_per_student'],key,time_text,'public_education_funding','Public K-12 education funding',{'citizen':name,'education_version':VERSION})
    age=int(rec.get('age',0))
    if age>=18 and int(rec.get('education_level',0))<1:
        rec['education_level']=1;rec['education']=EDU_LABELS[1]
        if 'High School Diploma' not in rec.setdefault('credentials',[]):rec['credentials'].append('High School Diploma')
        rec['active_enrollment']=None;rec['status']='not_enrolled'
        career_rec['education_level']=1;career_rec['education']=EDU_LABELS[1]
        append_event('high_school_completed',citizen=name,world_week=key)


def finance_program_week(name:str,rec:dict[str,Any],program:dict[str,Any],career_rec:dict[str,Any],hardship:int,key:str,time_text:str,finctx:tuple[Any,Any,Any]|None)->tuple[int,int,int]:
    tuition=max(0,int(program.get('tuition_week',0)))
    if tuition<=0:return 0,0,0
    rate=min(POLICY['max_scholarship_rate'],scholarship_rate(name,career_rec,hardship))
    planned_scholarship=int(round(tuition*rate));scholarship=0;cash_paid=0;borrowed=0
    if finctx and finctx[0]:
        fin,accounts,finstate=finctx;dst=institution_account(accounts,program['institution']);aid=citizen_account(fin,accounts,name)
        if planned_scholarship>0:
            scholarship=post_transfer(fin,accounts,finstate,'institution:dcb:municipal_treasury',dst,planned_scholarship,key,time_text,'education_scholarship','Education scholarship/grant',{'citizen':name,'program':program['title'],'education_version':VERSION})
        owed=max(0,tuition-scholarship)
        if aid:
            available=max(0,int(accounts.get(aid,{}).get('balance',0))-int(POLICY['cash_floor']))
            cash_paid=post_transfer(fin,accounts,finstate,aid,dst,min(owed,available),key,time_text,'tuition_payment','Education tuition payment',{'citizen':name,'program':program['title'],'education_version':VERSION})
        short=max(0,owed-cash_paid)
        if short>0:
            borrowed=post_transfer(fin,accounts,finstate,'institution:mccu:lending_reserve',dst,short,key,time_text,'student_loan_disbursement','Student education loan disbursement',{'citizen':name,'program':program['title'],'education_version':VERSION})
        rec['tuition_arrears']=int(rec.get('tuition_arrears',0))+max(0,short-borrowed)
    else:
        # Do not fabricate loan money if the Financial Network is unavailable.
        rec['tuition_arrears']=int(rec.get('tuition_arrears',0))+tuition
    rec['student_debt']=int(rec.get('student_debt',0))+borrowed
    rec['tuition_paid']=int(rec.get('tuition_paid',0))+cash_paid
    rec['scholarships_received']=int(rec.get('scholarships_received',0))+scholarship
    rec['loan_principal_borrowed']=int(rec.get('loan_principal_borrowed',0))+borrowed
    return cash_paid,scholarship,borrowed


def service_student_debt(name:str,rec:dict[str,Any],career_rec:dict[str,Any],key:str,time_text:str,finctx:tuple[Any,Any,Any]|None)->int:
    debt=max(0,int(rec.get('student_debt',0)))
    if debt<=0:return 0
    interest=max(1,int(round(debt*float(POLICY['weekly_student_loan_interest']))))
    rec['student_debt']=debt+interest
    if rec.get('active_enrollment'):return 0
    income=max(0,int(career_rec.get('weekly_income',0) or 0))
    if income<=0:return 0
    due=min(int(rec['student_debt']),max(int(POLICY['minimum_weekly_repayment']),int(round(income*float(POLICY['repayment_income_share'])))))
    if not finctx or not finctx[0]:return 0
    fin,accounts,finstate=finctx;aid=citizen_account(fin,accounts,name)
    if not aid:return 0
    paid=post_transfer(fin,accounts,finstate,aid,'institution:mccu:lending_reserve',due,key,time_text,'student_loan_repayment','Student loan repayment',{'citizen':name,'education_version':VERSION})
    rec['student_debt']=max(0,int(rec['student_debt'])-paid)
    if paid:append_event('student_loan_payment',citizen=name,amount=paid,balance=rec['student_debt'],world_week=key)
    return paid


def sync_career(name:str,rec:dict[str,Any],career_state:dict[str,Any])->None:
    cr=(career_state.setdefault('citizens',{})).get(name)
    if not isinstance(cr,dict):return
    cr['education_level']=int(rec.get('education_level',1));cr['education']=str(rec.get('education') or EDU_LABELS.get(int(rec.get('education_level',1)),'Unknown'))
    cr['skills']=dict(rec.get('skills') or {});cr['credentials']=list(rec.get('credentials') or [])
    enr=rec.get('active_enrollment')
    cr['education_program']=enr.get('title') if isinstance(enr,dict) else None
    cr['student_debt']=int(rec.get('student_debt',0))


def build_summary(state:dict[str,Any]|None=None)->dict[str,Any]:
    state=state or read_json(STATE_PATH,{'citizens':{}})
    citizens=state.get('citizens',{}) if isinstance(state,dict) else {}
    vals=[r for r in citizens.values() if isinstance(r,dict)] if isinstance(citizens,dict) else []
    enrolled=[r for r in vals if isinstance(r.get('active_enrollment'),dict)]
    bypath=Counter();byinst=Counter();levels=Counter();skills=defaultdict(list)
    debt=[];top_debt=[]
    for r in vals:
        levels[str(int(r.get('education_level',0)))]+=1
        e=r.get('active_enrollment')
        if isinstance(e,dict):
            p=program_by_runtime_id(str(e.get('program_id') or ''))
            bypath[str((p or {}).get('pathway') or e.get('pathway') or 'Unknown')]+=1
            byinst[str(e.get('institution_id') or '')]+=1
        d=max(0,int(r.get('student_debt',0) or 0));debt.append(d)
        if d:top_debt.append({'name':r.get('name'),'student_debt':d,'education':r.get('education'),'program':(e or {}).get('title') if isinstance(e,dict) else None})
        for k,v in (r.get('skills') or {}).items():
            try:skills[str(k)].append(float(v))
            except Exception:pass
    top_skills=sorted(({'skill':k,'average':round(sum(v)/len(v),1),'citizens':len(v)} for k,v in skills.items() if v),key=lambda x:x['average'],reverse=True)[:20]
    inst_rows=[]
    for inst in INSTITUTIONS:
        inst_rows.append({**inst,'enrolled':int(byinst.get(inst['id'],0))})
    recent=tail_events(60)
    last_key=state.get('last_processed_week')
    week_events=[e for e in recent if e.get('world_week')==last_key]
    summary={
        'version':VERSION,'updated_at':utc_now(),'world_week':last_key,'citizens_tracked':len(vals),
        'enrolled':len(enrolled),'k12_students':sum(1 for r in enrolled if (r.get('active_enrollment') or {}).get('pathway')=='K-12'),
        'adult_learners':sum(1 for r in enrolled if int(r.get('age',0))>=18),'apprentices':sum(1 for r in enrolled if (r.get('active_enrollment') or {}).get('pathway')=='Apprenticeship'),
        'education_levels':dict(levels),'pathways':dict(bypath),'institutions':inst_rows,'program_count':len(PROGRAMS),'programs':PROGRAMS,
        'credentials_awarded_total':sum(len(r.get('completed_programs') or []) for r in vals),
        'student_debt_total':sum(debt),'median_student_debt':int(median([x for x in debt if x])) if any(debt) else 0,
        'borrowers':sum(1 for x in debt if x>0),'highest_student_debt':sorted(top_debt,key=lambda x:x['student_debt'],reverse=True)[:15],
        'top_skills':top_skills,
        'tuition_paid_week':sum(int(e.get('amount',0)) for e in week_events if e.get('event')=='tuition_paid'),
        'scholarships_week':sum(int(e.get('amount',0)) for e in week_events if e.get('event')=='scholarship_awarded'),
        'completions_week':sum(1 for e in week_events if e.get('event') in {'program_completed','high_school_completed'}),
        'recent_events':recent,
        'principles':{
            'education_is_persistent':True,'protected_traits_never_used_for_access':True,'existing_education_grandfathered':True,
            'career_qualifications_sync_from_education':True,'skills_influence_future_job_matching':True,'student_debt_uses_financial_network':True,
            'public_k12_is_city_funded':True,'lifelong_learning_supported':True,
        }
    }
    write_json(SUMMARY_PATH,summary);return summary


def initialize()->dict[str,Any]:
    EDU.mkdir(parents=True,exist_ok=True)
    write_json(INSTITUTIONS_PATH,{'version':VERSION,'institutions':INSTITUTIONS})
    write_json(PROGRAMS_PATH,{'version':VERSION,'programs':PROGRAMS})
    year,week=current_year_week();key=week_key(year,week)
    state=read_json(STATE_PATH,{'version':VERSION,'citizens':{},'last_processed_week':None})
    if not isinstance(state,dict):state={'version':VERSION,'citizens':{},'last_processed_week':None}
    state['version']=VERSION;state.setdefault('citizens',{})
    career=read_json(CAREER_STATE,{'citizens':{}})
    for pdir in sorted((WORLD/'persona').iterdir()) if (WORLD/'persona').exists() else []:
        if not pdir.is_dir():continue
        name=pdir.name;profile=read_profile(name)
        if not profile:continue
        if name not in state['citizens']:
            state['citizens'][name]=seed_record(name,profile,year)
            append_event('education_seeded',citizen=name,education=state['citizens'][name]['education'],world_week=key)
        sync_career(name,state['citizens'][name],career)
    # Critical: installation never charges the current week or advances a course.
    if state.get('last_processed_week') is None:state['last_processed_week']=key
    state['updated_at']=utc_now();write_json(STATE_PATH,state);write_json(CAREER_STATE,career)
    return build_summary(state)


def process_week(world:Any)->None:
    state=read_json(STATE_PATH,{'version':VERSION,'citizens':{},'last_processed_week':None})
    t=world.clock.get_time();year=int(getattr(t,'year',2045));week=int(getattr(t,'week',1));key=week_key(year,week);time_text=str(t)
    if state.get('last_processed_week')==key:
        build_summary(state);return
    career=read_json(CAREER_STATE,{'citizens':{}});catalog_raw=read_json(CAREER_CATALOG,{});catalog=[x for x in catalog_raw.get('careers',[]) if isinstance(x,dict)] if isinstance(catalog_raw,dict) else []
    finctx=finance_context(world)
    totals={'tuition':0,'scholarships':0,'borrowed':0,'repaid':0,'completions':0}
    byname={getattr(a,'name',''):a for a in getattr(world,'agents',[])}
    names=set((state.get('citizens') or {}).keys())|set(byname.keys())
    for name in sorted(n for n in names if n):
        profile=read_profile(name)
        if not profile:continue
        rec=state.setdefault('citizens',{}).get(name)
        if not isinstance(rec,dict):rec=seed_record(name,profile,year);state['citizens'][name]=rec
        rec['age']=age_for(name,profile,year);rec['education_weeks_since_v172']=int(rec.get('education_weeks_since_v172',0))+1
        cr=(career.setdefault('citizens',{})).get(name)
        if not isinstance(cr,dict):cr={};career['citizens'][name]=cr
        maybe_enroll(name,rec,profile,cr,catalog,year,week)
        e=rec.get('active_enrollment')
        if isinstance(e,dict):
            p=program_by_runtime_id(str(e.get('program_id') or ''))
            if p:
                if p.get('pathway')=='K-12':
                    process_k12(name,rec,p,cr,year,key,finctx,time_text)
                else:
                    hid,hardship,_=household_pressure(name)
                    paid,scholar,borrow=finance_program_week(name,rec,p,cr,hardship,key,time_text,finctx)
                    totals['tuition']+=paid;totals['scholarships']+=scholar;totals['borrowed']+=borrow
                    if paid:append_event('tuition_paid',citizen=name,program=p['title'],amount=paid,world_week=key)
                    if scholar:append_event('scholarship_awarded',citizen=name,program=p['title'],amount=scholar,world_week=key)
                    if borrow:append_event('student_loan_borrowed',citizen=name,program=p['title'],amount=borrow,balance=rec.get('student_debt',0),world_week=key)
                    gain=skill_gain(p)
                    for tag in p.get('skills',[]):rec.setdefault('skills',{})[str(tag)]=min(300.0,round(float(rec['skills'].get(str(tag),20))+gain,2))
                    e['weeks_completed']=int(e.get('weeks_completed',0))+1
                    # Financial pressure can cause a temporary stop-out, but not a
                    # permanent lockout. The learner may re-enroll later.
                    rng=stable_rng(name,year,week,'education-progress')
                    dropout_chance=0.001+(0.012 if hardship>=80 else 0.004 if hardship>=60 else 0)
                    if rng.random()<dropout_chance:
                        rec['active_enrollment']=None;rec['status']='not_enrolled';rec['last_event']='stopped_out'
                        append_event('education_stop_out',citizen=name,program=p['title'],household=hid,world_week=key)
                    elif int(e.get('weeks_completed',0))>=int(e.get('weeks_required',p['duration_weeks'])):
                        complete_program(name,rec,p,cr,key);totals['completions']+=1
        totals['repaid']+=service_student_debt(name,rec,cr,key,time_text,finctx)
        sync_career(name,rec,career)
    state['last_processed_week']=key;state['updated_at']=utc_now();write_json(STATE_PATH,state);write_json(CAREER_STATE,career)
    if finctx and finctx[0]:
        fin,accounts,finstate=finctx;fin._save_accounts(accounts);fin._write_json(fin.STATE_PATH,finstate)
        try:fin._build_summary(world)
        except Exception:pass
    build_summary(state)
    try:world.logger.info('[EDU172] education tick complete: citizens=%d enrolled=%d tuition=%d scholarships=%d borrowed=%d repaid=%d completions=%d',len(state.get('citizens',{})),sum(1 for r in state.get('citizens',{}).values() if isinstance(r.get('active_enrollment'),dict)),totals['tuition'],totals['scholarships'],totals['borrowed'],totals['repaid'],totals['completions'])
    except Exception:pass


def education_context(name:str)->str:
    s=read_json(STATE_PATH,{});r=(s.get('citizens') or {}).get(name,{}) if isinstance(s,dict) else {}
    if not r:return ''
    e=r.get('active_enrollment');top=sorted((r.get('skills') or {}).items(),key=lambda x:float(x[1]),reverse=True)[:6]
    lines=[f'## Agentopia Education & Skills Economy v{VERSION}',f"- Education: {r.get('education','Unknown')}; credentials: {', '.join(r.get('credentials',[])[:5]) or 'none recorded'}."]
    if isinstance(e,dict):lines.append(f"- Current learning: {e.get('title')} at {INSTITUTION_BY_ID.get(e.get('institution_id'),{}).get('name',e.get('institution_id'))}; progress {int(e.get('weeks_completed',0))}/{int(e.get('weeks_required',0))} weeks.")
    else:lines.append('- Current learning: not enrolled in a formal program.')
    if top:lines.append('- Strongest recorded skills: '+', '.join(f'{k} {float(v):.0f}/300' for k,v in top)+'.')
    lines.append(f"- Student education debt: ${int(r.get('student_debt',0)):,}.")
    lines.append('- Education is a choice and opportunity, not destiny. You may pursue college, trades, apprenticeships, certifications, retraining, graduate education or no additional formal schooling depending on goals and circumstances.')
    lines.append('- Gender, race, ethnicity, religion and other protected traits are never used to determine educational access, qualification or career eligibility.')
    return '\n'.join(lines)


def apply_runtime_patches()->None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.world.world import World
    if not getattr(DataManager.character_prompt,'_agentopia_education_v172',False):
        original=DataManager.character_prompt
        def education_prompt(self):
            base=original(self)
            try:return str(base)+'\n\n'+education_context(self.char)
            except Exception:return base
        education_prompt._agentopia_education_v172=True;DataManager.character_prompt=education_prompt
    # Education executes BEFORE the existing v1.7.1 -> v1.7.0 -> Career chain.
    # Completed credentials/skills are therefore available to Career Economy for
    # the same new week's applications. Installation protects the current week.
    if not getattr(World._before_week_start,'_agentopia_education_v172',False):
        original_before=World._before_week_start
        def education_before(self):
            try:process_week(self)
            except Exception as e:
                try:self.logger.warning('[EDU172] education week failed: %s',e)
                except Exception:pass
            return original_before(self)
        education_before._agentopia_education_v172=True;World._before_week_start=education_before


def status()->None:
    s=initialize();print(f'Agentopia Detroit Education & Skills Economy v{VERSION}')
    print('Tracked citizens:',s.get('citizens_tracked'),'Enrolled:',s.get('enrolled'),'K-12:',s.get('k12_students'),'Adult learners:',s.get('adult_learners'),'Apprentices:',s.get('apprentices'))
    print('Programs:',s.get('program_count'),'Credentials awarded:',s.get('credentials_awarded_total'))
    print('Student debt:',s.get('student_debt_total'),'Borrowers:',s.get('borrowers'),'Median debt:',s.get('median_student_debt'))
    print('State:',EDU)


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['init','status'],nargs='?',default='status');args=ap.parse_args()
    if args.command=='init':initialize()
    status()
