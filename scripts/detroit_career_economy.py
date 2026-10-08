#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / 'data' / 'detroit_persistent'
CAREER = WORLD / 'career'
CATALOG_PATH = CAREER / 'catalog.json'
STATE_PATH = CAREER / 'state.json'
EVENTS_PATH = CAREER / 'events.ndjson'
SUMMARY_PATH = CAREER / 'summary.json'
BUSINESSES_PATH = CAREER / 'businesses.json'
VACANCIES_PATH = CAREER / 'vacancies.json'
VERSION = '1.6.1.4'

INCOME_BANDS = {
    1: (220, 325),
    2: (280, 400),
    3: (340, 475),
    4: (400, 575),
    5: (500, 700),
    6: (600, 850),
    7: (750, 1100),
    8: (950, 1500),
    9: (1300, 2000),
    10: (1800, 4000),
}
EDU_LEVELS = ['none', 'high_school', 'certificate', 'associate', 'bachelor', 'graduate_professional']
EDU_LABELS = {
    0: 'No formal requirement', 1: 'High school / equivalent', 2: 'Certificate / trade',
    3: 'Associate / technical degree', 4: "Bachelor's degree", 5: 'Graduate / professional degree',
}

SECTOR_SKILLS = {
    'Executive & Ownership': ['leadership', 'strategy', 'business'],
    'Medicine & Health': ['healthcare', 'science', 'empathy'],
    'AI, Software & Technology': ['programming', 'systems_thinking', 'analysis'],
    'Cybersecurity & Intelligence': ['cybersecurity', 'analysis', 'networking'],
    'Engineering & Manufacturing': ['engineering', 'troubleshooting', 'safety'],
    'Mobility, Robotics & Infrastructure': ['engineering', 'automation', 'systems_thinking'],
    'Law, Government & Public Safety': ['law', 'communication', 'judgment'],
    'Science & Research': ['research', 'analysis', 'science'],
    'Education': ['teaching', 'communication', 'planning'],
    'Creative, Media & Entertainment': ['creativity', 'communication', 'design'],
    'Construction & Skilled Trades': ['trades', 'troubleshooting', 'safety'],
    'Business & Operations': ['business', 'planning', 'communication'],
    'Community, Hospitality & Everyday Economy': ['service', 'communication', 'organization'],
}

SECTOR_ORGS = {
    'Executive & Ownership': ['Great Lakes Ventures', 'Detroit Future Holdings', 'Riverfront Capital', 'Motor City Enterprise Group'],
    'Medicine & Health': ['Detroit Community Health Network', 'Great Lakes Medical Center', 'Riverfront Health Cooperative'],
    'AI, Software & Technology': ['Michigan Central AI Works', 'Great Lakes Software Collective', 'Detroit Sovereign Compute Lab'],
    'Cybersecurity & Intelligence': ['Detroit Cyber Defense Cooperative', 'Great Lakes Security Lab', 'Civic Digital Trust Office'],
    'Engineering & Manufacturing': ['Detroit Advanced Manufacturing Works', 'Great Lakes Engineering Group', 'Motor City Fabrication'],
    'Mobility, Robotics & Infrastructure': ['Michigan Central Mobility District', 'Detroit Autonomous Systems Cooperative', 'Great Lakes Robotics Works'],
    'Law, Government & Public Safety': ['City of Detroit 2045', 'Wayne Civic Justice Center', 'Detroit Public Safety Network'],
    'Science & Research': ['Great Lakes Research Institute', 'Detroit Applied Science Lab', 'Michigan Future Research Center'],
    'Education': ['Detroit Learning Network', 'University of Michigan-Flint Detroit Lab', 'Great Lakes Technical Academy'],
    'Creative, Media & Entertainment': ['Detroit Creative Cooperative', 'Motown Future Media', 'Riverfront Arts Collective'],
    'Construction & Skilled Trades': ['Detroit Trades Cooperative', 'Great Lakes Infrastructure Services', 'Motor City Construction Guild'],
    'Business & Operations': ['Detroit Commerce Group', 'Great Lakes Operations Network', 'Eastern Market Enterprise Services'],
    'Community, Hospitality & Everyday Economy': ['Eastern Market Cooperative', 'Detroit Neighborhood Services', 'Riverfront Hospitality Group'],
}

CAREER_GROUPS: list[tuple[str, list[str]]] = [
    ('Executive & Ownership', [
        'Founder/CEO','Technology Company Founder','Manufacturing Company Owner','Investment Fund Partner','Private Equity Partner',
        'Venture Capital Partner','Investment Banker','Hedge Fund Manager','Commercial Real Estate Developer','Global Corporate CEO',
        'Chief Operating Officer','Chief Financial Officer','Chief Technology Officer','Chief Information Officer','Chief Information Security Officer',
        'Chief AI Officer','Management Consultant Partner','Corporate Attorney Partner','Financial Advisor/Wealth Manager','Entrepreneur/Small Business Owner',
    ]),
    ('Medicine & Health', [
        'Neurosurgeon','Cardiothoracic Surgeon','Orthopedic Surgeon','Plastic Surgeon','Anesthesiologist','Radiologist','Psychiatrist',
        'Emergency Physician','Family Physician','Dentist','Orthodontist','Pharmacist','Nurse Practitioner','Physician Assistant',
        'Registered Nurse','Physical Therapist','Occupational Therapist','Clinical Psychologist','Medical Laboratory Scientist','Emergency Medical Technician/Paramedic',
    ]),
    ('AI, Software & Technology', [
        'AI Research Scientist','Machine Learning Engineer','AI Systems Architect','Robotics Engineer','Software Architect','Principal Software Engineer',
        'Cybersecurity Architect','Security Engineer','Cloud Architect','Data Scientist','Data Engineer','Database Architect','DevOps Engineer',
        'Site Reliability Engineer','Mobile Application Developer','Game Developer','UX/UI Designer','Systems Administrator','Network Engineer','IT Support Specialist',
    ]),
    ('Cybersecurity & Intelligence', [
        'Chief Security Officer','Security Operations Director','Penetration Tester','Digital Forensics Investigator','Incident Response Specialist',
        'Threat Intelligence Analyst','Security Analyst','Identity & Access Engineer','OT/Industrial Cybersecurity Engineer','Privacy Engineer',
    ]),
    ('Engineering & Manufacturing', [
        'Aerospace Engineer','Automotive Engineer','Electrical Engineer','Mechanical Engineer','Chemical Engineer','Civil Engineer','Structural Engineer',
        'Industrial Engineer','Biomedical Engineer','Materials Scientist','Semiconductor Engineer','Battery Engineer','Nuclear Engineer','Energy Systems Engineer',
        'Manufacturing Engineer','Automation Engineer','CNC Programmer','Industrial Maintenance Technician','Machinist','Quality Engineer',
    ]),
    ('Mobility, Robotics & Infrastructure', [
        'Autonomous Vehicle Engineer','Autonomous Fleet Manager','Mobility Systems Architect','Drone Systems Engineer','Drone Pilot','Robotics Technician',
        'Humanoid Robotics Engineer','Smart Infrastructure Engineer','Vehicle Cybersecurity Engineer','EV Powertrain Engineer','EV Battery Technician',
        'Charging Infrastructure Engineer','Traffic Systems Engineer','Railway Systems Engineer','Logistics Automation Engineer',
    ]),
    ('Law, Government & Public Safety', [
        'Judge','Attorney','Prosecutor','Public Defender','Corporate Compliance Officer','City Manager','Government Policy Analyst','Diplomat',
        'Intelligence Analyst','Police Chief','Police Detective','Police Officer','Firefighter','Emergency Management Director','Public Safety Dispatcher',
    ]),
    ('Science & Research', [
        'Physicist','Quantum Computing Scientist','Chemist','Biochemist','Molecular Biologist','Geneticist','Environmental Scientist','Climate Scientist',
        'Geologist','Astronomer','Research Scientist','Laboratory Technician','Agricultural Scientist','Food Scientist','Research Assistant',
    ]),
    ('Education', [
        'University Professor','College Lecturer','School Principal','K-12 Teacher','Special Education Teacher','Career/Technical Education Instructor',
        'Instructional Designer','AI Education Specialist','Academic Advisor','Teaching Assistant',
    ]),
    ('Creative, Media & Entertainment', [
        'Film Director','Film Producer','Actor','Music Producer','Recording Artist','Musician','Game Designer','Animator','Graphic Designer',
        'Photographer','Journalist','Author','Content Creator','Fashion Designer','Interior Designer',
    ]),
    ('Construction & Skilled Trades', [
        'Architect','Construction Manager','General Contractor','Electrician','Plumber','HVAC Technician','Carpenter','Welder','Elevator Technician',
        'Solar Installer','Wind Turbine Technician','Heavy Equipment Operator','Building Inspector','Automotive Technician','Diesel Technician',
    ]),
    ('Business & Operations', [
        'Product Manager','Project Manager','Operations Manager','Human Resources Manager','Marketing Manager','Sales Manager','Account Executive',
        'Business Analyst','Supply Chain Manager','Procurement Specialist',
    ]),
    ('Community, Hospitality & Everyday Economy', [
        'Restaurant Owner','Executive Chef','Chef','Restaurant Manager','Hotel Manager','Real Estate Agent','Insurance Agent','Social Worker','Counselor',
        'Barber/Hairstylist','Cosmetologist','Fitness Trainer','Retail Manager','Barista','Customer Service Specialist',
    ]),
]


def _tier_for(title: str, sector: str) -> int:
    t = title.lower()
    if t in {'barista','customer service specialist','teaching assistant','research assistant'}: return 1
    if any(k in t for k in ['founder/ceo','technology company founder','investment fund partner','private equity partner','venture capital partner','hedge fund manager','global corporate ceo']): return 10
    if any(k in t for k in ['chief ', 'neurosurgeon','cardiothoracic','orthopedic surgeon','plastic surgeon','anesthesiologist','radiologist','investment banker','corporate attorney partner','management consultant partner']): return 9
    if any(k in t for k in ['physician','dentist','orthodontist','psychiatrist','commercial real estate developer','ai research scientist','ai systems architect','software architect','principal software engineer','aerospace engineer','nuclear engineer','judge','film director','film producer']): return 8
    if any(k in t for k in ['pharmacist','nurse practitioner','physician assistant','machine learning engineer','cybersecurity architect','cloud architect','data scientist','security operations director','attorney','city manager','university professor','architect','construction manager','product manager']): return 7
    if any(k in t for k in ['registered nurse','physical therapist','occupational therapist','clinical psychologist','engineer','scientist','penetration tester','digital forensics','incident response','privacy engineer','police chief','diplomat','school principal','college lecturer','music producer','restaurant owner','general contractor','operations manager','sales manager']): return 6
    if any(k in t for k in ['data engineer','database architect','devops','site reliability','security analyst','intelligence analyst','prosecutor','public defender','research scientist','instructional designer','ai education specialist','executive chef','hotel manager','real estate agent','financial advisor','wealth manager','supply chain manager']): return 5
    if any(k in t for k in ['developer','designer','administrator','network engineer','technician','quality engineer','policy analyst','detective','firefighter','teacher','journalist','author','project manager','business analyst','marketing manager','human resources manager','insurance agent','social worker','counselor','retail manager']): return 4
    if any(k in t for k in ['electrician','plumber','hvac','carpenter','welder','machinist','paramedic','police officer','laboratory technician','photographer','musician','chef','barber','cosmetologist','fitness trainer','account executive']): return 3
    if any(k in t for k in ['assistant','barista','customer service','dispatcher','drone pilot','installer','operator']): return 2
    return 5


def _education_for(title: str, sector: str) -> int:
    t = title.lower()
    if any(k in t for k in ['surgeon','physician','dentist','orthodontist','psychiatrist','anesthesiologist','radiologist','pharmacist','clinical psychologist','judge','attorney','prosecutor','public defender','university professor']): return 5
    if any(k in t for k in ['scientist','engineer','architect','data scientist','machine learning','chief ','director','manager','analyst','designer','developer','journalist','teacher','principal','diplomat','financial advisor','product manager','project manager']): return 4
    if any(k in t for k in ['registered nurse','technician','paramedic','electrician','plumber','hvac','welder','machinist','operator','police officer','firefighter','barber','cosmetologist']): return 2
    if any(k in t for k in ['assistant','barista','customer service','retail manager','chef','musician','actor','content creator','real estate agent','insurance agent']): return 1
    return 3


def _experience_for(title: str, tier: int) -> int:
    t = title.lower()
    if any(k in t for k in ['chief ', 'partner','global corporate ceo','founder/ceo']): return 10
    if tier >= 9: return 8
    if tier >= 7: return 5
    if tier >= 5: return 2
    return 0


def build_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rank = 1
    for sector, titles in CAREER_GROUPS:
        for title in titles:
            tier = _tier_for(title, sector)
            lo, hi = INCOME_BANDS[tier]
            rows.append({
                'id': f'career-{rank:03d}', 'rank': rank, 'title': title, 'sector': sector,
                'tier': tier, 'weekly_income_min': lo, 'weekly_income_max': hi,
                'minimum_education_level': _education_for(title, sector),
                'minimum_education': EDU_LABELS[_education_for(title, sector)],
                'minimum_experience_years': _experience_for(title, tier),
                'skill_tags': SECTOR_SKILLS[sector],
            })
            rank += 1
    assert len(rows) == 200, len(rows)
    return rows

CATALOG = build_catalog()
BY_ID = {x['id']: x for x in CATALOG}
BY_TITLE = {re.sub(r'[^a-z0-9]+', ' ', x['title'].lower()).strip(): x for x in CATALOG}


def utc_now() -> str: return datetime.now(timezone.utc).isoformat()

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

def append_event(kind: str, **payload: Any) -> None:
    CAREER.mkdir(parents=True, exist_ok=True)
    row = {'at': utc_now(), 'event': kind, **payload}
    with EVENTS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')

def tail_events(n: int = 40) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists(): return []
    out = []
    for line in EVENTS_PATH.read_text(encoding='utf-8', errors='replace').splitlines()[-n:]:
        try:
            x = json.loads(line)
            if isinstance(x, dict): out.append(x)
        except Exception: pass
    return out

def stable_rng(*parts: Any) -> random.Random:
    seed = '|'.join(str(x) for x in parts)
    h = hashlib.sha256(seed.encode('utf-8')).hexdigest()
    return random.Random(int(h[:16], 16))

def latest_profile_path(name: str) -> Path | None:
    pdir = WORLD / 'persona' / name / 'profile'
    if not pdir.exists(): return None
    files = sorted(pdir.glob('year=*.json'), key=lambda p: p.name)
    return files[-1] if files else None

def read_profile(name: str) -> tuple[Path | None, dict[str, Any]]:
    p = latest_profile_path(name)
    if p is None: return None, {}
    d = read_json(p, {})
    return p, d if isinstance(d, dict) else {}

def current_year_week() -> tuple[int, int]:
    cp = read_json(WORLD / 'checkpoint.json', {})
    def walk(x: Any) -> tuple[int | None, int | None]:
        if isinstance(x, dict):
            y = x.get('year'); w = x.get('week')
            if isinstance(y, int) and isinstance(w, int): return y, w
            for v in x.values():
                a,b = walk(v)
                if a is not None and b is not None: return a,b
        elif isinstance(x, list):
            for v in x:
                a,b=walk(v)
                if a is not None and b is not None:return a,b
        return None,None
    y,w = walk(cp)
    return int(y or 2045), int(w or 1)

def normalize_title(s: str) -> str:
    return re.sub(r'[^a-z0-9]+',' ',str(s).lower()).strip()

def match_career(title: str) -> dict[str, Any] | None:
    nt = normalize_title(title)
    if not nt: return None
    if nt in BY_TITLE: return BY_TITLE[nt]
    aliases = {
        'software developer':'Mobile Application Developer', 'barista':'Barista','teacher':'K-12 Teacher','nurse':'Registered Nurse',
        'security analyst':'Security Analyst','data analyst':'Business Analyst','research analyst':'Research Scientist','mechanic':'Automotive Technician',
        'small business owner':'Entrepreneur/Small Business Owner','social worker':'Social Worker','journalist':'Journalist','artist':'Graphic Designer',
        'chef':'Chef','designer':'Graphic Designer','electrician':'Electrician','logistics coordinator':'Supply Chain Manager',
    }
    if nt in aliases: return BY_TITLE.get(normalize_title(aliases[nt]))
    tokens = set(nt.split())
    best = None; score = 0
    for row in CATALOG:
        rt = set(normalize_title(row['title']).split())
        overlap = len(tokens & rt)
        if overlap > score:
            score = overlap; best = row
    return best if score > 0 else None

def education_level(profile: dict[str, Any], matched: dict[str, Any] | None) -> int:
    vals=[]
    for key in ('education','highest_education','degree','education_level'):
        v=profile.get(key)
        if isinstance(v, (str,int,float)): vals.append(str(v).lower())
        elif isinstance(v, dict): vals += [str(x).lower() for x in v.values()]
        elif isinstance(v, list): vals += [str(x).lower() for x in v]
    text=' '.join(vals)
    if any(k in text for k in ['phd','doctorate','doctoral','md ','m.d.','jd ','j.d.','master']): return 5
    if any(k in text for k in ['bachelor','b.s.','b.a.','university','college degree']): return 4
    if 'associate' in text: return 3
    if any(k in text for k in ['certificate','certification','trade school','apprentice']): return 2
    if any(k in text for k in ['high school','secondary']): return 1
    # Existing citizens are grandfathered into their present job requirements.
    return int(matched.get('minimum_education_level', 1)) if matched else 1

def age_for(profile: dict[str, Any], year: int) -> int:
    by=profile.get('birth_year')
    try: return max(0, year-int(by))
    except Exception: return 30

def profile_text(profile: dict[str, Any]) -> str:
    bits=[]
    for k in ('brief_introduction','details','core_motivation','values','preferences'):
        bits.append(str(profile.get(k) or ''))
    pos=profile.get('position') or {}
    if isinstance(pos,dict): bits += [str(pos.get('role') or ''),str(pos.get('description') or '')]
    sk=profile.get('init_skills') or {}
    if isinstance(sk,dict): bits += list(map(str,sk.keys()))
    return ' '.join(bits).lower()
def trait(profile: dict[str, Any], key: str, default: int=55) -> int:
    for parent in ('talents','personality_traits'):
        q=(profile.get(parent) or {}).get('quantitative',{}) if isinstance(profile.get(parent),dict) else {}
        try:
            if key in q:return int(q[key])
        except Exception:pass
    return default

def career_affinity(profile: dict[str, Any], career: dict[str, Any]) -> float:
    text=profile_text(profile)
    score=35.0
    for tag in career.get('skill_tags',[]):
        if str(tag).replace('_',' ') in text or str(tag) in text: score += 10
    sec=str(career.get('sector','')).lower()
    words=set(re.findall(r'[a-z]{4,}',sec))
    score += min(20, 4*sum(1 for w in words if w in text))
    if career['sector']=='Creative, Media & Entertainment': score += (trait(profile,'creativity')-50)*0.22
    if career['sector'] in {'Executive & Ownership','Business & Operations'}: score += (trait(profile,'leadership')-50)*0.20
    if career['sector'] in {'Medicine & Health','Education','Community, Hospitality & Everyday Economy'}: score += (trait(profile,'empathy')-50)*0.16
    if career['sector'] in {'AI, Software & Technology','Cybersecurity & Intelligence','Science & Research','Engineering & Manufacturing'}: score += (trait(profile,'thinking')-50)*0.18
    return max(0.0,min(100.0,score))

def qualified(rec: dict[str,Any], career: dict[str,Any]) -> bool:
    return int(rec.get('education_level',1)) >= int(career.get('minimum_education_level',1)) and float(rec.get('experience_years',0)) >= float(career.get('minimum_experience_years',0))

def skill_match_score(rec: dict[str,Any], career: dict[str,Any]) -> float:
    skills=rec.get('skills') or {}
    tags=[str(x) for x in career.get('skill_tags',[]) or []]
    if not isinstance(skills,dict) or not tags:
        return 0.0
    vals=[]
    for tag in tags:
        try: vals.append(float(skills.get(tag,0)))
        except Exception: pass
    if not vals or max(vals)<=0:
        return 0.0
    avg=sum(vals)/len(vals)
    target=min(145.0,25.0+12.0*int(career.get('tier',2)))
    return max(-18.0,min(22.0,8.0+(avg-target)/5.0))

def choose_aspirations(profile: dict[str,Any], rec: dict[str,Any]) -> list[str]:
    cur_tier=int(rec.get('tier',2))
    candidates=[]
    for c in CATALOG:
        if int(c['tier']) > cur_tier+3: continue
        gap=max(0,int(c['minimum_education_level'])-int(rec.get('education_level',1)))
        if gap>1: continue
        score=career_affinity(profile,c)+(c['tier']-cur_tier)*2-gap*10
        candidates.append((score,c['id']))
    candidates.sort(reverse=True)
    return [cid for _,cid in candidates[:3]]

def salary_for(career: dict[str,Any], rng: random.Random, experience: float=0) -> int:
    lo=int(career['weekly_income_min']); hi=int(career['weekly_income_max'])
    frac=min(0.95,max(0.05,0.25+experience/35.0+rng.random()*0.25))
    return int(round(lo+(hi-lo)*frac))

def protected_role(profile: dict[str,Any]) -> bool:
    role=str((profile.get('position') or {}).get('role') or '').lower() if isinstance(profile.get('position'),dict) else ''
    return profile.get('world_role')=='faction_leader' or role in {'founder and guardian commander','founder and supreme architect'}

def seed_record(name: str, profile: dict[str,Any], year: int) -> dict[str,Any]:
    pos=profile.get('position') if isinstance(profile.get('position'),dict) else {}
    role=str(pos.get('role') or 'Unemployed')
    org=str(pos.get('organization') or '')
    income=int(pos.get('weekly_income') or 0)
    matched=match_career(role)
    tier=int(matched['tier']) if matched else next((t for t,(lo,hi) in INCOME_BANDS.items() if lo<=income<=hi),2)
    edu=education_level(profile,matched)
    age=age_for(profile,year)
    exp=max(0.0,min(40.0,(age-18)*0.65))
    status='employed' if income>0 or (role and role.lower()!='unemployed') else 'unemployed'
    if age<18: status='student'
    rec={
        'name':name,'status':status,'career_id': matched['id'] if matched else None,'current_title':role,
        'catalog_title':matched['title'] if matched else role,'sector':matched['sector'] if matched else 'Legacy / Other',
        'tier':tier,'weekly_income':income,'organization':org,'education_level':edu,'education':EDU_LABELS.get(edu,'Unknown'),
        'experience_years':round(exp,1),'tenure_weeks':0,'career_satisfaction':stable_rng(name,'sat').randint(48,82),
        'performance':max(35,min(95,round((trait(profile,'responsibility')+trait(profile,'intelligence')+trait(profile,'communication'))/3))),
        'lifetime_earnings_since_v1614':0,'career_history':[{'week':'seed','title':role,'organization':org,'weekly_income':income}],
        'aspirations':[],'training':None,'business_id':None,'protected_current_role':protected_role(profile),
    }
    rec['aspirations']=choose_aspirations(profile,rec)
    return rec

def build_vacancies(year:int,week:int,count:int=60)->list[dict[str,Any]]:
    rng=stable_rng('vacancies',year,week)
    weighted=[]
    for c in CATALOG:
        w=4 if c['sector'] in {'AI, Software & Technology','Engineering & Manufacturing','Mobility, Robotics & Infrastructure','Medicine & Health'} else 2
        if c['tier']>=9:w=1
        weighted.extend([c]*w)
    out=[]
    for i in range(count):
        c=rng.choice(weighted); org=rng.choice(SECTOR_ORGS[c['sector']]); lo,hi=c['weekly_income_min'],c['weekly_income_max']
        out.append({'vacancy_id':f'Y{year}-W{week:02d}-V{i+1:03d}','career_id':c['id'],'title':c['title'],'sector':c['sector'],'organization':org,'weekly_income':rng.randint(int(lo),int(hi)),'tier':c['tier'],'minimum_education_level':c['minimum_education_level'],'minimum_experience_years':c['minimum_experience_years']})
    write_json(VACANCIES_PATH,{'updated_at':utc_now(),'world_year':year,'world_week':week,'vacancies':out})
    return out

def _businesses()->dict[str,Any]:
    d=read_json(BUSINESSES_PATH,{'businesses':{}})
    if not isinstance(d,dict):d={'businesses':{}}
    d.setdefault('businesses',{})
    return d

def start_business(name:str,rec:dict[str,Any],profile:dict[str,Any],year:int,week:int)->None:
    b=_businesses(); rng=stable_rng(name,year,week,'business')
    sector=rec.get('sector') if rec.get('sector') in SECTOR_ORGS else 'Business & Operations'
    bid='biz-'+hashlib.sha1(f'{name}|{year}|{week}'.encode()).hexdigest()[:10]
    if bid in b['businesses']:return
    label=f"{name.split()[0]} {rng.choice(['Works','Labs','Group','Studio','Ventures','Services'])}"
    value=rng.randint(3000,18000)
    b['businesses'][bid]={'business_id':bid,'name':label,'owner':name,'sector':sector,'founded_week':f'Y{year}-W{week:02d}','estimated_value':value,'employees':1,'status':'operating'}
    write_json(BUSINESSES_PATH,b)
    owner=BY_TITLE[normalize_title('Entrepreneur/Small Business Owner')]
    rec.update({'business_id':bid,'status':'self_employed','career_id':owner['id'],'current_title':owner['title'],'catalog_title':owner['title'],'sector':owner['sector'],'tier':owner['tier'],'organization':label,'weekly_income':salary_for(owner,rng,rec.get('experience_years',0))})
    rec['career_history'].append({'week':f'Y{year}-W{week:02d}','title':owner['title'],'organization':label,'event':'business_started','weekly_income':rec['weekly_income']})
    append_event('business_started',citizen=name,business=label,weekly_income=rec['weekly_income'])

def sync_profile(name:str,profile:dict[str,Any],rec:dict[str,Any],year:int,agent:Any|None=None)->None:
    pos=profile.get('position') if isinstance(profile.get('position'),dict) else {}
    pos=dict(pos)
    pos['weekly_income']=int(rec.get('weekly_income',0)) if rec.get('status') not in {'retired','unemployed'} else 0
    pos['role']=str(rec.get('current_title') or 'Unemployed')
    pos['organization']=str(rec.get('organization') or '')
    pos['type']='work' if rec.get('status') in {'employed','self_employed'} else str(rec.get('status') or 'unemployed')
    pos['description']=f"Career Economy v{VERSION}: {pos['role']} in {rec.get('sector','Agentopia economy')}."
    if 'weekly_delta_skills' not in pos:
        c=BY_ID.get(rec.get('career_id'))
        pos['weekly_delta_skills']={k:0.2 for k in (c.get('skill_tags',[]) if c else [])[:2]}
    profile['position']=pos
    profile['career']={k:rec.get(k) for k in ('status','career_id','current_title','sector','tier','weekly_income','organization','education','experience_years','career_satisfaction','performance','aspirations','business_id')}
    pdir=WORLD/'persona'/name/'profile'; pdir.mkdir(parents=True,exist_ok=True); p=pdir/f'year={year}.json'
    if not p.exists():
        old=latest_profile_path(name)
        if old is not None:p.write_text(old.read_text(encoding='utf-8'),encoding='utf-8')
    write_json(p,profile)
    if agent is not None:
        try:
            if hasattr(agent.dm,'write_profile'): agent.dm.write_profile(profile,year=year)
        except Exception: pass
        for attr in ('profile','_profile','current_profile'):
            try:
                if hasattr(agent.dm,attr): setattr(agent.dm,attr,profile)
            except Exception:pass

def process_training(name:str,rec:dict[str,Any],year:int,week:int)->None:
    # AGENTOPIA_EDUCATION_SKILL_BRIDGE_V172
    if (WORLD/'education'/'state.json').exists():
        return
    tr=rec.get('training')
    if not isinstance(tr,dict):return
    tr['weeks_completed']=int(tr.get('weeks_completed',0))+1
    if tr['weeks_completed']>=int(tr.get('weeks_required',26)):
        old=int(rec.get('education_level',1)); new=min(5,old+1)
        rec['education_level']=new; rec['education']=EDU_LABELS[new]; rec['training']=None
        append_event('education_advanced',citizen=name,education=EDU_LABELS[new],world_week=f'Y{year}-W{week:02d}')

def choose_vacancy(name:str,profile:dict[str,Any],rec:dict[str,Any],vacancies:list[dict[str,Any]])->dict[str,Any]|None:
    ranked=[]
    for v in vacancies:
        c=BY_ID.get(v.get('career_id'))
        if not c or not qualified(rec,c):continue
        score=career_affinity(profile,c)+skill_match_score(rec,c)+stable_rng(name,v['vacancy_id']).random()*8
        if int(c['tier'])>int(rec.get('tier',2))+3:score-=20
        ranked.append((score,v))
    ranked.sort(key=lambda x:x[0],reverse=True)
    return ranked[0][1] if ranked else None

def take_job(name:str,profile:dict[str,Any],rec:dict[str,Any],vacancy:dict[str,Any],year:int,week:int,event:str)->None:
    c=BY_ID[vacancy['career_id']]
    old=rec.get('current_title')
    rec.update({'status':'employed','career_id':c['id'],'current_title':c['title'],'catalog_title':c['title'],'sector':c['sector'],'tier':c['tier'],'weekly_income':int(vacancy['weekly_income']),'organization':vacancy['organization'],'tenure_weeks':0})
    rec['career_satisfaction']=min(95,max(40,int(rec.get('career_satisfaction',60))+stable_rng(name,year,week,event).randint(-4,12)))
    rec['career_history'].append({'week':f'Y{year}-W{week:02d}','title':c['title'],'organization':vacancy['organization'],'event':event,'weekly_income':rec['weekly_income']})
    rec['aspirations']=choose_aspirations(profile,rec)
    append_event(event,citizen=name,from_title=old,to_title=c['title'],organization=vacancy['organization'],weekly_income=rec['weekly_income'])

def process_citizen(name:str,profile:dict[str,Any],rec:dict[str,Any],vacancies:list[dict[str,Any]],year:int,week:int)->None:
    rng=stable_rng(name,year,week,'career')
    rec['tenure_weeks']=int(rec.get('tenure_weeks',0))+1
    rec['experience_years']=round(float(rec.get('experience_years',0))+1/52,2)
    rec['lifetime_earnings_since_v1614']=int(rec.get('lifetime_earnings_since_v1614',0))+max(0,int(rec.get('weekly_income',0)))
    process_training(name,rec,year,week)
    if rec.get('protected_current_role'):return
    age=age_for(profile,year)
    if age<18:
        rec['status']='student';rec['weekly_income']=0;return
    if rec.get('status')=='retired':return
    if age>=70 and rng.random()<0.12 or age>=67 and rng.random()<0.035:
        rec.update({'status':'retired','weekly_income':0,'organization':'','current_title':'Retired'})
        rec['career_history'].append({'week':f'Y{year}-W{week:02d}','event':'retired','title':'Retired'})
        append_event('retired',citizen=name,age=age);return
    # Finish unemployment first.
    if rec.get('status')=='unemployed':
        if rng.random()<0.55:
            v=choose_vacancy(name,profile,rec,vacancies)
            if v:take_job(name,profile,rec,v,year,week,'hired')
        return
    # Small but real layoff risk.
    if rng.random()<0.002:
        old=rec.get('current_title');rec.update({'status':'unemployed','weekly_income':0,'organization':'','current_title':'Unemployed','tenure_weeks':0})
        append_event('laid_off',citizen=name,from_title=old);return
    # Promotion / raise cadence.
    if int(rec['tenure_weeks'])%8==0 and rng.random() < (0.08 + max(0,int(rec.get('performance',60))-60)/250):
        c=BY_ID.get(rec.get('career_id'))
        if c:
            old=int(rec.get('weekly_income',0)); cap=int(c['weekly_income_max']); inc=max(10,int(old*rng.uniform(0.05,0.11)))
            rec['weekly_income']=min(cap,old+inc);rec['performance']=min(99,int(rec.get('performance',60))+rng.randint(1,3))
            append_event('promoted_or_raised',citizen=name,title=rec.get('current_title'),old_weekly_income=old,new_weekly_income=rec['weekly_income'])
    # Career change for dissatisfied citizens.
    if int(rec['tenure_weeks'])%13==0 and int(rec.get('career_satisfaction',60))<68 and rng.random()<0.12:
        v=choose_vacancy(name,profile,rec,vacancies)
        if v and v['title']!=rec.get('current_title'):take_job(name,profile,rec,v,year,week,'career_change')
    # Retraining toward an aspiration.
    if not rec.get('training') and int(rec['tenure_weeks'])%13==0 and rec.get('aspirations'):
        target=BY_ID.get(rec['aspirations'][0]); gap=int(target['minimum_education_level'])-int(rec.get('education_level',1)) if target else 0
        if gap>0 and rng.random()<0.18:
            rec['training']={'target_career_id':target['id'],'weeks_required':26,'weeks_completed':0}
            append_event('training_started',citizen=name,target=target['title'],required_weeks=26)
    # Entrepreneurship requires confidence/leadership and is deliberately rare.
    if int(rec['tenure_weeks'])%26==0 and age>=23 and trait(profile,'leadership')>=72 and trait(profile,'confidence')>=65 and rng.random()<0.04:
        start_business(name,rec,profile,year,week)

def build_summary(state:dict[str,Any]|None=None)->dict[str,Any]:
    state=state or read_json(STATE_PATH,{'citizens':{}})
    people=state.get('citizens',{}) if isinstance(state,dict) else {}
    vals=list(people.values()) if isinstance(people,dict) else []
    employed=[r for r in vals if r.get('status') in {'employed','self_employed'}]
    incomes=[int(r.get('weekly_income',0)) for r in employed]
    sectors=Counter(str(r.get('sector') or 'Other') for r in employed)
    tiers=Counter(int(r.get('tier',0)) for r in employed)
    businesses=_businesses().get('businesses',{})
    vac=read_json(VACANCIES_PATH,{'vacancies':[]}).get('vacancies',[])
    top=sorted([{'name':r.get('name'),'title':r.get('current_title'),'organization':r.get('organization'),'weekly_income':int(r.get('weekly_income',0)),'tier':int(r.get('tier',0))} for r in employed],key=lambda x:x['weekly_income'],reverse=True)[:15]
    out={'version':VERSION,'updated_at':utc_now(),'catalog_count':len(CATALOG),'employed':len(employed),'unemployed':sum(1 for r in vals if r.get('status')=='unemployed'),'students':sum(1 for r in vals if r.get('status')=='student'),'retired':sum(1 for r in vals if r.get('status')=='retired'),'entrepreneurs':sum(1 for r in vals if r.get('status')=='self_employed'),'median_weekly_income':int(median(incomes)) if incomes else 0,'mean_weekly_income':round(sum(incomes)/len(incomes),1) if incomes else 0,'tier_distribution':{str(k):v for k,v in sorted(tiers.items())},'sector_distribution':dict(sectors.most_common()),'top_earners':top,'business_count':len(businesses),'businesses':list(businesses.values())[:20],'vacancy_count':len(vac),'vacancies':vac[:30],'recent_events':tail_events(40),'catalog':CATALOG,'principles':{'protected_traits_never_used_for_eligibility':True,'existing_roles_grandfathered':True,'education_and_experience_gates':True,'career_changes_are_persistent':True,'income_bands_are_agentopia_normalized_not_real_world_salary_quotes':True}}
    write_json(SUMMARY_PATH,out);return out

def initialize() -> dict[str,Any]:
    CAREER.mkdir(parents=True,exist_ok=True)
    write_json(CATALOG_PATH,{'version':VERSION,'count':200,'rank_basis':'Agentopia earning potential, training barrier and ownership upside; not a literal global salary ranking.','income_bands':INCOME_BANDS,'careers':CATALOG})
    state=read_json(STATE_PATH,{'version':VERSION,'citizens':{},'last_world_week':None})
    if not isinstance(state,dict):state={'version':VERSION,'citizens':{},'last_world_week':None}
    state['version']=VERSION;state.setdefault('citizens',{})
    year,week=current_year_week()
    for pdir in sorted((WORLD/'persona').iterdir()) if (WORLD/'persona').exists() else []:
        if not pdir.is_dir():continue
        name=pdir.name;_,profile=read_profile(name)
        if not profile:continue
        if name not in state['citizens']:
            state['citizens'][name]=seed_record(name,profile,year)
            append_event('career_seeded',citizen=name,title=state['citizens'][name]['current_title'],weekly_income=state['citizens'][name]['weekly_income'])
    if state.get('last_world_week') is None:
        state['last_world_week']=f'Y{year}-W{week:02d}'
    state['updated_at']=utc_now();write_json(STATE_PATH,state)
    build_vacancies(year,week)
    return build_summary(state)

def week_start(world:Any)->None:
    state=read_json(STATE_PATH,{'version':VERSION,'citizens':{},'last_world_week':None})
    t=world.clock.get_time();year=int(getattr(t,'year',2045));week=int(getattr(t,'week',1));key=f'Y{year}-W{week:02d}'
    vacancies=build_vacancies(year,week)
    # Avoid duplicate career decisions when the engine restarts inside the same simulated week.
    if state.get('last_world_week')==key:
        build_summary(state);return
    byname={getattr(a,'name',''):a for a in getattr(world,'agents',[])}
    for name,agent in byname.items():
        _,profile=read_profile(name)
        if not profile:continue
        rec=state.setdefault('citizens',{}).get(name)
        if not isinstance(rec,dict):rec=seed_record(name,profile,year);state['citizens'][name]=rec
        process_citizen(name,profile,rec,vacancies,year,week)
        sync_profile(name,profile,rec,year,agent)
    state['last_world_week']=key;state['updated_at']=utc_now();write_json(STATE_PATH,state);build_summary(state)
    try:world.logger.info('[CAREER1614] career economy tick complete: citizens=%d vacancies=%d',len(state.get('citizens',{})),len(vacancies))
    except Exception:pass

def career_context(name:str)->str:
    s=read_json(STATE_PATH,{});r=(s.get('citizens') or {}).get(name,{}) if isinstance(s,dict) else {}
    if not r:return ''
    aspirations=[]
    for cid in r.get('aspirations',[])[:3]:
        c=BY_ID.get(cid)
        if c:aspirations.append(c['title'])
    lines=[f'## Agentopia Career Economy v{VERSION}',f"- Employment: {r.get('status','unknown')} — {r.get('current_title','Unknown')} @ {r.get('organization') or 'n/a'}.",f"- Weekly income: ${int(r.get('weekly_income',0)):,}; career tier {int(r.get('tier',0))}/10; satisfaction {int(r.get('career_satisfaction',0))}/100; performance {int(r.get('performance',0))}/100.",f"- Education: {r.get('education','Unknown')}; experience: {r.get('experience_years',0)} years."]
    if aspirations:lines.append('- Aspirational careers: '+', '.join(aspirations)+'.')
    if r.get('training'):lines.append('- You are currently retraining toward a new career. Career changes must respect education, experience and available openings.')
    lines.append('- Careers are choices, not destiny. You may seek promotion, change fields, retrain, start a business, be laid off, recover, or retire as your life evolves.')
    lines.append('- Gender, race, ethnicity, religion and other protected traits are never career eligibility criteria.')
    return '\n'.join(lines)

def overlay_profile(name: str, profile: Any) -> Any:
    if not isinstance(profile, dict):
        return profile
    try:
        state = read_json(STATE_PATH, {})
        rec = (state.get('citizens') or {}).get(name, {}) if isinstance(state, dict) else {}
        if not rec:
            return profile
        out = dict(profile)
        pos = dict(out.get('position') or {}) if isinstance(out.get('position'), dict) else {}
        pos['weekly_income'] = int(rec.get('weekly_income', 0)) if rec.get('status') not in {'retired', 'unemployed'} else 0
        pos['role'] = str(rec.get('current_title') or pos.get('role') or 'Unemployed')
        pos['organization'] = str(rec.get('organization') or pos.get('organization') or '')
        pos['type'] = 'work' if rec.get('status') in {'employed', 'self_employed'} else str(rec.get('status') or 'unemployed')
        out['position'] = pos
        return out
    except Exception:
        return profile

def apply_runtime_patches()->None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.world.world import World
    if not getattr(DataManager.character_prompt,'_agentopia_career_v1614',False):
        original=DataManager.character_prompt
        def career_prompt(self):
            base=original(self)
            try:return str(base)+'\n\n'+career_context(self.char)
            except Exception:return base
        career_prompt._agentopia_career_v1614=True;DataManager.character_prompt=career_prompt
    if hasattr(DataManager, 'read_profile') and not getattr(DataManager.read_profile, '_agentopia_career_v1614', False):
        original_read_profile = DataManager.read_profile
        def career_read_profile(self, *a, **k):
            prof = original_read_profile(self, *a, **k)
            try:
                return overlay_profile(self.char, prof)
            except Exception:
                return prof
        career_read_profile._agentopia_career_v1614 = True
        DataManager.read_profile = career_read_profile
    if hasattr(DataManager, 'get_position') and not getattr(DataManager.get_position, '_agentopia_career_v1614', False):
        original_get_position = DataManager.get_position
        def career_get_position(self, *a, **k):
            try:
                state = read_json(STATE_PATH, {})
                rec = (state.get('citizens') or {}).get(self.char, {})
                if rec:
                    return {
                        'weekly_income': int(rec.get('weekly_income', 0)) if rec.get('status') not in {'retired','unemployed'} else 0,
                        'role': rec.get('current_title'), 'organization': rec.get('organization'),
                        'type': 'work' if rec.get('status') in {'employed','self_employed'} else rec.get('status'),
                    }
            except Exception:
                pass
            return original_get_position(self, *a, **k)
        career_get_position._agentopia_career_v1614 = True
        DataManager.get_position = career_get_position
    if hasattr(DataManager,'get_weekly_income') and not getattr(DataManager.get_weekly_income,'_agentopia_career_v1614',False):
        original_income=DataManager.get_weekly_income
        def career_income(self,*a,**k):
            try:
                s=read_json(STATE_PATH,{});r=(s.get('citizens') or {}).get(self.char,{})
                if r:return int(r.get('weekly_income',0))
            except Exception:pass
            return original_income(self,*a,**k)
        career_income._agentopia_career_v1614=True;DataManager.get_weekly_income=career_income
    if not getattr(World._before_week_start,'_agentopia_career_v1614',False):
        original_before=World._before_week_start
        def career_before(self):
            try:week_start(self)
            except Exception as e:
                try:self.logger.warning('[CAREER1614] week_start failed: %s',e)
                except Exception:pass
            return original_before(self)
        career_before._agentopia_career_v1614=True;World._before_week_start=career_before

def status()->None:
    s=initialize()
    print(f'Agentopia Career Economy v{VERSION}')
    print('Catalog:',s.get('catalog_count'),'professions')
    print('Employed:',s.get('employed'),'Unemployed:',s.get('unemployed'),'Students:',s.get('students'),'Retired:',s.get('retired'))
    print('Entrepreneurs:',s.get('entrepreneurs'),'Businesses:',s.get('business_count'),'Vacancies:',s.get('vacancy_count'))
    print('Median weekly income:',s.get('median_weekly_income'))
    print('State:',CAREER)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['init','status'],nargs='?',default='status');args=ap.parse_args()
    if args.command=='init':initialize()
    status()
