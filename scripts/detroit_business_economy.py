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
BUS = WORLD / 'business_economy'
STATE_PATH = BUS / 'state.json'
SUMMARY_PATH = BUS / 'summary.json'
EVENTS_PATH = BUS / 'events.jsonl'
LEDGER_PATH = BUS / 'ledger.jsonl'
OPENINGS_PATH = BUS / 'openings.json'
VERSION = '1.7.1'

CAREER_STATE = WORLD / 'career' / 'state.json'
CAREER_CATALOG = WORLD / 'career' / 'catalog.json'
CAREER_BUSINESSES = WORLD / 'career' / 'businesses.json'
HUMAN_STATE = WORLD / 'human_economy' / 'state.json'
HUMAN_SUMMARY = WORLD / 'human_economy' / 'summary.json'

# Fictional 2045 Agentopia parameters. These are simulation controls, not
# forecasts of future Detroit business law, taxes, wages or industry margins.
POLICY = {
    'business_profit_tax_rate': 0.10,
    'weekly_interest_rate': 0.0022,
    'minimum_cash_weeks': 2.0,
    'distress_layoff_weeks': 3,
    'bankruptcy_weeks': 8,
    'consumer_revenue_capture': 0.78,
    'contract_revenue_share': 0.18,
    'max_debt_to_payroll': 20.0,
    'growth_opening_profit_weeks': 3,
}

CATEGORY_SOURCE = {
    'housing': 'institution:merchant:merchant_settlement',
    'food': 'institution:merchant:merchant_settlement',
    'utilities': 'institution:dcb:utility_revenue',
    'transport': 'institution:agentpay:mobility_settlement',
    'healthcare': 'institution:glcb:health_billing',
    'insurance': 'institution:insurance:claims_reserve',
    'communications': 'institution:merchant:merchant_settlement',
    'discretionary': 'institution:merchant:merchant_settlement',
}

SECTOR_CONSUMER_MIX = {
    'Executive & Ownership': {'housing':0.25,'discretionary':0.15},
    'Medicine & Health': {'healthcare':1.00},
    'AI, Software & Technology': {'communications':0.65,'discretionary':0.10},
    'Cybersecurity & Intelligence': {'communications':0.25},
    'Engineering & Manufacturing': {'housing':0.18,'transport':0.18},
    'Mobility, Robotics & Infrastructure': {'transport':0.85},
    'Law, Government & Public Safety': {},
    'Science & Research': {},
    'Education': {},
    'Creative, Media & Entertainment': {'discretionary':0.75},
    'Construction & Skilled Trades': {'housing':0.75},
    'Business & Operations': {'communications':0.25,'discretionary':0.15},
    'Community, Hospitality & Everyday Economy': {'food':0.90,'discretionary':0.70,'communications':0.10},
}

SECTOR_COST_RATIO = {
    'Executive & Ownership':0.18,'Medicine & Health':0.30,'AI, Software & Technology':0.18,
    'Cybersecurity & Intelligence':0.17,'Engineering & Manufacturing':0.42,
    'Mobility, Robotics & Infrastructure':0.38,'Law, Government & Public Safety':0.18,
    'Science & Research':0.28,'Education':0.16,'Creative, Media & Entertainment':0.24,
    'Construction & Skilled Trades':0.40,'Business & Operations':0.20,
    'Community, Hospitality & Everyday Economy':0.45,
}

ANCHORS = [
    ('Detroit Housing & Neighborhood Cooperative','Executive & Ownership','cooperative','housing'),
    ('Eastern Market Food Network','Community, Hospitality & Everyday Economy','cooperative','food'),
    ('Great Lakes Utilities','Engineering & Manufacturing','public_utility','utilities'),
    ('Detroit Mobility Services','Mobility, Robotics & Infrastructure','cooperative','transport'),
    ('Riverfront Health Services','Medicine & Health','nonprofit','healthcare'),
    ('Great Lakes Mutual Services','Business & Operations','mutual','insurance'),
    ('Detroit Fiber & Communications','AI, Software & Technology','cooperative','communications'),
    ('Motown Retail & Entertainment','Creative, Media & Entertainment','private','discretionary'),
    ('Detroit Advanced Manufacturing Works','Engineering & Manufacturing','private','contracts'),
    ('Great Lakes Software Collective','AI, Software & Technology','cooperative','contracts'),
    ('Detroit Trades Cooperative','Construction & Skilled Trades','cooperative','contracts'),
    ('Motor City Logistics Network','Business & Operations','private','contracts'),
]

PUBLIC_HINTS = ('city of detroit','public safety','civic','justice center','government','municipal','fire','police')
NONPROFIT_HINTS = ('community health','learning network','university','academy','research institute','community services')
FACTION_ORGS = {'ThAI Guardians','Obsidian Network'}


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


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def tail_jsonl(path: Path, n: int = 40) -> list[dict[str, Any]]:
    if not path.exists(): return []
    try: lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()[-n:]
    except Exception: return []
    out=[]
    for line in lines:
        try:
            row=json.loads(line)
            if isinstance(row,dict): out.append(row)
        except Exception: pass
    return out


def stable_rng(*parts: Any) -> random.Random:
    seed = hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest()
    return random.Random(int(seed[:16],16))


def current_year_week() -> tuple[int,int]:
    cp=read_json(WORLD/'checkpoint.json',{})
    text=str(cp.get('current_time') or cp.get('time') or '')
    m=re.search(r'Y(\d+)-W(\d+)',text)
    if m:return int(m.group(1)),int(m.group(2))
    return 2045,1


def world_key(year:int,week:int)->str: return f'Y{year}-W{week:02d}'


def slug(text:str)->str:
    return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')[:40]


def business_id(name:str)->str:
    return 'biz-'+slug(name)[:28]+'-'+hashlib.sha1(name.encode()).hexdigest()[:7]


def entity_type(name:str)->str:
    low=name.lower()
    if any(x in low for x in PUBLIC_HINTS): return 'public'
    if any(x in low for x in NONPROFIT_HINTS): return 'nonprofit'
    if 'cooperative' in low or 'collective' in low or 'guild' in low: return 'cooperative'
    return 'private'


def career_doc()->dict[str,Any]:
    d=read_json(CAREER_STATE,{'citizens':{}})
    return d if isinstance(d,dict) else {'citizens':{}}


def catalog()->list[dict[str,Any]]:
    d=read_json(CAREER_CATALOG,{'careers':[]})
    return d.get('careers',[]) if isinstance(d,dict) and isinstance(d.get('careers'),list) else []


def human_last_week()->dict[str,Any]:
    d=read_json(HUMAN_STATE,{})
    return d.get('last_week',{}) if isinstance(d,dict) and isinstance(d.get('last_week'),dict) else {}


def classify_sector(org:str, employees:list[dict[str,Any]])->str:
    sectors=Counter(str(e.get('sector') or '') for e in employees if e.get('sector'))
    if sectors:return sectors.most_common(1)[0][0]
    low=org.lower()
    if 'health' in low or 'medical' in low:return 'Medicine & Health'
    if 'mobility' in low or 'transit' in low or 'robot' in low:return 'Mobility, Robotics & Infrastructure'
    if 'school' in low or 'academy' in low or 'university' in low or 'learning' in low:return 'Education'
    if 'security' in low or 'cyber' in low:return 'Cybersecurity & Intelligence'
    if 'manufactur' in low or 'fabrication' in low or 'engineering' in low:return 'Engineering & Manufacturing'
    if 'creative' in low or 'media' in low or 'arts' in low:return 'Creative, Media & Entertainment'
    if 'construction' in low or 'trades' in low:return 'Construction & Skilled Trades'
    return 'Business & Operations'


def opening_capital(payroll:int, entity:str, name:str)->int:
    rng=stable_rng('opening-capital',name)
    multiplier={'public':20,'nonprofit':10,'cooperative':9,'private':8,'mutual':12,'public_utility':16}.get(entity,8)
    return max(12000, payroll*multiplier + rng.randint(4000,22000))


def default_business(name:str,sector:str,etype:str,owner:str|None=None,anchor_category:str|None=None,payroll:int=0)->dict[str,Any]:
    bid=business_id(name); cap=opening_capital(payroll,etype,name)
    return {
        'business_id':bid,'name':name,'sector':sector,'entity_type':etype,'owner':owner,
        'status':'operating','founded_week':'legacy_2045' if not owner else None,
        'anchor_category':anchor_category,'opening_capital':cap,'cash':cap,'debt':0,
        'revenue_week':0,'payroll_week':0,'operating_cost_week':0,'interest_week':0,'tax_week':0,'profit_week':0,
        'revenue_total':0,'payroll_total':0,'tax_total':0,'profit_total':0,
        'profitable_weeks':0,'loss_weeks':0,'distress_weeks':0,'payroll_shortfall_weeks':0,
        'employees':0,'active_payroll_employees':0,'estimated_value':max(10000,cap*2),
        'reputation':stable_rng(name,'rep').randint(55,88),'demand_index':1.0,'supply_chain_index':1.0,
        'inventory_weeks':round(stable_rng(name,'inv').uniform(1.5,5.0),2),'last_processed_week':None,
    }


def employee_map(cdoc:dict[str,Any])->dict[str,list[dict[str,Any]]]:
    by=defaultdict(list)
    for name,rec in (cdoc.get('citizens') or {}).items():
        if not isinstance(rec,dict) or rec.get('status') not in {'employed','self_employed'}:continue
        org=str(rec.get('organization') or '').strip()
        if not org or org in FACTION_ORGS:continue
        row=dict(rec);row['name']=name;by[org].append(row)
    return dict(by)


def sync_business_registry(state:dict[str,Any])->dict[str,Any]:
    businesses=state.setdefault('businesses',{})
    cdoc=career_doc(); byorg=employee_map(cdoc)
    imported=read_json(CAREER_BUSINESSES,{'businesses':{}})
    imported_b=(imported.get('businesses') or {}) if isinstance(imported,dict) else {}
    owner_by_org={str(r.get('name')):str(r.get('owner')) for r in imported_b.values() if isinstance(r,dict) and r.get('name') and r.get('owner')}
    for org,employees in byorg.items():
        bid=business_id(org)
        payroll=sum(max(0,int(x.get('weekly_income',0))) for x in employees)
        if bid not in businesses:
            sector=classify_sector(org,employees);etype=entity_type(org);owner=owner_by_org.get(org)
            businesses[bid]=default_business(org,sector,etype,owner=owner,payroll=payroll)
            businesses[bid]['founded_week']='legacy_2045' if not owner else str(next((r.get('founded_week') for r in imported_b.values() if isinstance(r,dict) and r.get('name')==org),None) or 'legacy_2045')
        b=businesses[bid];b['employees']=len(employees);b['sector']=b.get('sector') or classify_sector(org,employees)
        if owner_by_org.get(org):b['owner']=owner_by_org[org]
    # Always maintain a small set of Detroit anchor enterprises so every Human
    # Economy spending category has somewhere real to flow.
    for name,sector,etype,cat in ANCHORS:
        bid=business_id(name)
        if bid not in businesses:businesses[bid]=default_business(name,sector,etype,anchor_category=cat,payroll=0)
    return state


def finance_runtime(world:Any):
    try:
        import detroit_financial_system as fin
        accounts=fin._accounts();fstate=fin._state();fin._ensure_base_accounts(accounts)
        return fin,accounts,fstate
    except Exception:return None,{},{}


def business_account(accounts:dict[str,Any],b:dict[str,Any])->str:
    aid=f"business:{b['business_id']}:operating"
    accounts.setdefault(aid,{
        'account_id':aid,'name':f"{b.get('name')} Operating",'owner':b.get('owner') or b.get('name'),
        'owner_type':'business','bank_id':'glcb','balance':int(b.get('opening_capital',0)),'frozen':0,'status':'open'
    })
    return aid


def transfer(fin_ctx:tuple[Any,dict[str,Any],dict[str,Any]],src:str,dst:str,amount:int,key:str,time_text:str,tx_type:str,description:str,meta:dict[str,Any]|None=None,allow_overdraft:bool=False)->int:
    fin,accounts,fstate=fin_ctx
    if fin is None:return 0
    try:return int(fin._transfer(accounts,fstate,src,dst,max(0,int(amount)),key,time_text,tx_type,description,meta or {},allow_overdraft=allow_overdraft))
    except Exception:return 0


def save_finance(fin_ctx,world:Any)->None:
    fin,accounts,fstate=fin_ctx
    if fin is None:return
    try:
        fstate['updated_at']=utc_now();fin._save_accounts(accounts);fin._write_json(fin.STATE_PATH,fstate);fin._build_summary(world)
    except Exception:pass


def active_employees(world:Any,cdoc:dict[str,Any])->dict[str,list[dict[str,Any]]]:
    active={str(a.name) for a in getattr(world,'agents',[])}
    out=defaultdict(list)
    for name,rec in (cdoc.get('citizens') or {}).items():
        if name not in active or not isinstance(rec,dict) or rec.get('status') not in {'employed','self_employed'}:continue
        org=str(rec.get('organization') or '').strip()
        if not org or org in FACTION_ORGS:continue
        row=dict(rec);row['name']=name;out[org].append(row)
    return dict(out)


def sector_demand_adjustment(sector:str,year:int,week:int)->float:
    rng=stable_rng('sector-demand',sector,year,week)
    return max(0.82,min(1.20,1.0+rng.gauss(0,0.045)))


def allocate_consumer_revenue(businesses:dict[str,Any],last:dict[str,Any],fin_ctx,key,time_text)->dict[str,int]:
    spending=last.get('spending_categories',{}) if isinstance(last,dict) else {}
    allocated=Counter()
    operating=[b for b in businesses.values() if isinstance(b,dict) and b.get('status')=='operating']
    for category,source in CATEGORY_SOURCE.items():
        pool=int(float(spending.get(category,0))*POLICY['consumer_revenue_capture'])
        if pool<=0:continue
        candidates=[]
        for b in operating:
            mix=SECTOR_CONSUMER_MIX.get(str(b.get('sector')),{});w=float(mix.get(category,0))
            if str(b.get('anchor_category'))==category:w=max(w,1.20)
            if w>0:candidates.append((b,w*max(0.5,float(b.get('demand_index',1.0)))*max(0.4,int(b.get('reputation',60))/70)))
        if not candidates:continue
        total=sum(w for _,w in candidates)
        remaining=pool
        for i,(b,w) in enumerate(candidates):
            share=remaining if i==len(candidates)-1 else int(round(pool*w/total));remaining-=share
            if share<=0:continue
            aid=business_account(fin_ctx[1],b);posted=transfer(fin_ctx,source,aid,share,key,time_text,'business_revenue',f'{category.title()} customer revenue',{'business_id':b['business_id'],'category':category,'business_economy_version':VERSION})
            allocated[b['business_id']]+=posted
    return dict(allocated)


def institutional_revenue(b:dict[str,Any],payroll:int,fin_ctx,key,time_text,year:int,week:int)->int:
    et=str(b.get('entity_type') or 'private');sector=str(b.get('sector') or '')
    if et=='public':
        source='institution:dcb:municipal_treasury';target=int(payroll*1.35+220)
    elif et=='nonprofit':
        source='institution:glcb:bank_operations';target=int(payroll*0.72+180)
    elif et=='public_utility':
        source='institution:dcb:utility_revenue';target=int(payroll*1.15+180)
    elif et=='mutual':
        source='institution:insurance:claims_reserve';target=int(payroll*0.55+120)
    elif sector in {'AI, Software & Technology','Cybersecurity & Intelligence','Engineering & Manufacturing','Mobility, Robotics & Infrastructure','Science & Research','Construction & Skilled Trades','Business & Operations'}:
        source='institution:glcb:bank_operations';target=int((payroll*0.35+160)*POLICY['contract_revenue_share']*5.0)
    else:return 0
    target=int(target*sector_demand_adjustment(sector,year,week))
    return transfer(fin_ctx,source,business_account(fin_ctx[1],b),target,key,time_text,'institutional_revenue','Institutional contracts, grants or public-service funding',{'business_id':b['business_id'],'business_economy_version':VERSION})


def debt_service_and_borrow(b:dict[str,Any],aid:str,payroll:int,fin_ctx,key,time_text)->tuple[int,int]:
    accounts=fin_ctx[1];debt=max(0,int(b.get('debt',0)));interest=0;borrowed=0
    if debt>0:
        due=max(1,int(debt*POLICY['weekly_interest_rate']))
        interest=transfer(fin_ctx,aid,'institution:mccu:lending_reserve',due,key,time_text,'business_interest','Small-business/commercial debt interest',{'business_id':b['business_id']})
    cash=max(0,int(accounts.get(aid,{}).get('balance',0)))
    min_cash=int(max(300,payroll*POLICY['minimum_cash_weeks']))
    max_debt=int(max(5000,payroll*POLICY['max_debt_to_payroll']))
    if cash<min_cash and debt<max_debt and b.get('entity_type') not in {'public'}:
        want=min(max_debt-debt,max(0,min_cash-cash)+max(500,payroll))
        borrowed=transfer(fin_ctx,'institution:mccu:lending_reserve',aid,want,key,time_text,'business_loan','Commercial working-capital loan',{'business_id':b['business_id']})
        b['debt']=debt+borrowed
        if borrowed:append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'business_borrowed','business':b['name'],'amount':borrowed,'debt':b['debt']})
    return interest,borrowed


def sync_owner_valuation(b:dict[str,Any])->None:
    if not b.get('owner'):return
    d=read_json(CAREER_BUSINESSES,{'businesses':{}})
    if not isinstance(d,dict):return
    changed=False
    for rec in (d.get('businesses') or {}).values():
        if isinstance(rec,dict) and str(rec.get('name'))==str(b.get('name')):
            rec['estimated_value']=int(b.get('estimated_value',0));rec['employees']=int(b.get('employees',0));rec['status']=str(b.get('status'));rec['business_economy_version']=VERSION;changed=True
    if changed:write_json(CAREER_BUSINESSES,d)


def layoff_business(b:dict[str,Any],count:int,year:int,week:int,world:Any,reason:str)->int:
    if count<=0:return 0
    try:import detroit_career_economy as career
    except Exception:return 0
    cdoc=career_doc();people=cdoc.get('citizens',{});candidates=[]
    for name,rec in people.items():
        if not isinstance(rec,dict) or rec.get('organization')!=b.get('name') or rec.get('status') not in {'employed','self_employed'}:continue
        if rec.get('protected_current_role') or name==b.get('owner'):continue
        candidates.append((int(rec.get('performance',60)),name,rec))
    candidates.sort(key=lambda x:(x[0],x[1]))
    agents={str(a.name):a for a in getattr(world,'agents',[])};done=0
    for _,name,rec in candidates[:count]:
        old=rec.get('current_title');rec.update({'status':'unemployed','weekly_income':0,'organization':'','current_title':'Unemployed','tenure_weeks':0})
        rec.setdefault('career_history',[]).append({'week':world_key(year,week),'event':'business_layoff','title':old,'organization':b.get('name'),'reason':reason})
        try:
            _,prof=career.read_profile(name)
            if prof:career.sync_profile(name,prof,rec,year,agents.get(name))
        except Exception:pass
        append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':world_key(year,week),'event':'business_layoff','business':b.get('name'),'citizen':name,'from_title':old,'reason':reason});done+=1
    write_json(CAREER_STATE,cdoc)
    return done


def close_business(b:dict[str,Any],year:int,week:int,world:Any)->int:
    laid=layoff_business(b,999,year,week,world,'business_closed')
    b['status']='bankrupt';b['closed_week']=world_key(year,week);b['employees']=max(0,int(b.get('employees',0))-laid)
    append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':world_key(year,week),'event':'business_bankruptcy','business':b['name'],'debt':int(b.get('debt',0)),'layoffs':laid})
    return laid


def build_openings(businesses:dict[str,Any],year:int,week:int)->list[dict[str,Any]]:
    cats=catalog();bysector=defaultdict(list)
    for c in cats:
        if isinstance(c,dict) and int(c.get('tier',0))<=8:bysector[str(c.get('sector'))].append(c)
    openings=[]
    for b in businesses.values():
        if not isinstance(b,dict) or b.get('status')!='operating':continue
        if int(b.get('profitable_weeks',0))<POLICY['growth_opening_profit_weeks']:continue
        if int(b.get('profit_week',0))<=0:continue
        rng=stable_rng('opening',b['business_id'],year,week)
        count=1+(1 if int(b.get('profit_week',0))>1500 and rng.random()<0.35 else 0)
        choices=bysector.get(str(b.get('sector')),[])
        for i in range(count):
            if not choices:continue
            c=rng.choice(choices);lo=int(c.get('weekly_income_min',250));hi=int(c.get('weekly_income_max',500))
            openings.append({'vacancy_id':f"{world_key(year,week)}-B-{b['business_id'][-7:]}-{i+1}",'career_id':c.get('id'),'title':c.get('title'),'sector':c.get('sector'),'organization':b.get('name'),'weekly_income':rng.randint(lo,hi),'tier':int(c.get('tier',0)),'minimum_education_level':int(c.get('minimum_education_level',1)),'minimum_experience_years':float(c.get('minimum_experience_years',0)),'source':'business_economy','business_id':b.get('business_id')})
    write_json(OPENINGS_PATH,{'version':VERSION,'updated_at':utc_now(),'world_week':world_key(year,week),'vacancies':openings})
    return openings


def process_week(world:Any)->None:
    t=world.clock.get_time();year=int(getattr(t,'year',2045));week=int(getattr(t,'week',1));key=world_key(year,week);time_text=str(t)
    state=read_json(STATE_PATH,{'version':VERSION,'businesses':{},'last_processed_week':None,'cumulative':{}})
    if not isinstance(state,dict):state={'version':VERSION,'businesses':{},'last_processed_week':None,'cumulative':{}}
    sync_business_registry(state)
    if state.get('last_processed_week')==key:
        build_summary(state);return
    cdoc=career_doc();active_by_org=active_employees(world,cdoc);fin_ctx=finance_runtime(world);accounts=fin_ctx[1]
    for b in state['businesses'].values():business_account(accounts,b)
    consumer=allocate_consumer_revenue(state['businesses'],human_last_week(),fin_ctx,key,time_text)
    weekly=Counter();total_layoffs=0;bankruptcies=0
    for b in state['businesses'].values():
        if not isinstance(b,dict) or b.get('status')!='operating':continue
        employees=active_by_org.get(str(b.get('name')),[]);payroll=sum(max(0,int(r.get('weekly_income',0))) for r in employees)
        b['active_payroll_employees']=len(employees);b['employees']=max(int(b.get('employees',0)),len(employees))
        b['demand_index']=round(max(0.70,min(1.35,float(b.get('demand_index',1.0))*0.82+sector_demand_adjustment(str(b.get('sector')),year,week)*0.18)),3)
        srng=stable_rng(b['business_id'],'supply',year,week);b['supply_chain_index']=round(max(0.70,min(1.25,float(b.get('supply_chain_index',1.0))*0.85+(1+srng.gauss(0,0.04))*0.15)),3)
        aid=business_account(accounts,b);start_cash=int(accounts[aid].get('balance',0))
        rev=int(consumer.get(b['business_id'],0))+institutional_revenue(b,payroll,fin_ctx,key,time_text,year,week)
        # Non-consumer firms also receive bounded B2B demand; it is funded by bank operations, not fabricated directly into the company account.
        if rev < max(120,int(payroll*0.45)) and b.get('entity_type') not in {'public'}:
            target=max(0,int(payroll*0.28+stable_rng(b['business_id'],year,week,'b2b').randint(50,260)))
            rev += transfer(fin_ctx,'institution:glcb:bank_operations',aid,target,key,time_text,'b2b_revenue','Agentopia business-to-business contracts',{'business_id':b['business_id']})
        ratio=float(SECTOR_COST_RATIO.get(str(b.get('sector')),0.25));opex=max(35,int(rev*ratio))
        if float(b.get('supply_chain_index',1.0))<0.88:opex=int(opex*1.12)
        opex_paid=transfer(fin_ctx,aid,'system:consumption_sink',opex,key,time_text,'business_opex','Inventory, utilities, rent, supplies and operating expense',{'business_id':b['business_id']})
        payroll_paid=transfer(fin_ctx,aid,'system:employer_payroll',payroll,key,time_text,'business_payroll_funding','Employer funding of Agentopia payroll clearing',{'business_id':b['business_id']})
        interest,borrowed=debt_service_and_borrow(b,aid,payroll,fin_ctx,key,time_text)
        pretax=rev-opex_paid-payroll_paid-interest
        tax_due=max(0,int(pretax*POLICY['business_profit_tax_rate']))
        tax_paid=transfer(fin_ctx,aid,'institution:dcb:municipal_treasury',tax_due,key,time_text,'business_tax','Modeled Agentopia business-profit tax',{'business_id':b['business_id']})
        profit=rev-opex_paid-payroll_paid-interest-tax_paid
        b.update({'revenue_week':rev,'payroll_week':payroll_paid,'operating_cost_week':opex_paid,'interest_week':interest,'tax_week':tax_paid,'profit_week':profit})
        b['revenue_total']=int(b.get('revenue_total',0))+rev;b['payroll_total']=int(b.get('payroll_total',0))+payroll_paid;b['tax_total']=int(b.get('tax_total',0))+tax_paid;b['profit_total']=int(b.get('profit_total',0))+profit
        if profit>=0:b['profitable_weeks']=int(b.get('profitable_weeks',0))+1;b['loss_weeks']=0
        else:b['loss_weeks']=int(b.get('loss_weeks',0))+1;b['profitable_weeks']=0
        short=max(0,payroll-payroll_paid)
        if short>0:b['payroll_shortfall_weeks']=int(b.get('payroll_shortfall_weeks',0))+1
        else:b['payroll_shortfall_weeks']=0
        if profit<0 or short>0:b['distress_weeks']=int(b.get('distress_weeks',0))+1
        else:b['distress_weeks']=max(0,int(b.get('distress_weeks',0))-1)
        cash=int(accounts.get(aid,{}).get('balance',0));b['cash']=cash
        # Gradual principal repayment when liquidity is healthy.
        if int(b.get('debt',0))>0 and profit>0 and cash>max(1000,payroll*4):
            repay=min(int(b['debt']),max(50,int(profit*0.18)))
            paid=transfer(fin_ctx,aid,'institution:mccu:lending_reserve',repay,key,time_text,'business_debt_principal','Commercial loan principal repayment',{'business_id':b['business_id']})
            b['debt']=max(0,int(b['debt'])-paid);cash=int(accounts.get(aid,{}).get('balance',0));b['cash']=cash
        # Inventory moves with demand and supply conditions for goods-heavy sectors.
        goods_ratio=ratio
        b['inventory_weeks']=round(max(0.25,min(8.0,float(b.get('inventory_weeks',2.5))+0.25*float(b.get('supply_chain_index',1.0))-0.35*float(b.get('demand_index',1.0))*goods_ratio)),2)
        avg_profit=float(b.get('profit_total',0))/max(1,int(b.get('profitable_weeks',0))+int(b.get('loss_weeks',0)))
        b['estimated_value']=max(0,int(cash-int(b.get('debt',0))+max(0,rev)*8+max(-5000,avg_profit)*12))
        b['last_processed_week']=key
        if int(b.get('distress_weeks',0))>=POLICY['distress_layoff_weeks'] and b.get('entity_type') not in {'public'} and len(employees)>1:
            n=max(1,math.ceil(len(employees)*0.15));laid=layoff_business(b,n,year,week,world,'financial_distress');total_layoffs+=laid
            if laid:append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'business_restructuring','business':b['name'],'layoffs':laid,'distress_weeks':b['distress_weeks']})
        if int(b.get('distress_weeks',0))>=POLICY['bankruptcy_weeks'] and b.get('entity_type') not in {'public','public_utility'} and cash<max(500,payroll//2):
            total_layoffs+=close_business(b,year,week,world);bankruptcies+=1
        sync_owner_valuation(b)
        append_jsonl(LEDGER_PATH,{'time':utc_now(),'world_week':key,'business_id':b['business_id'],'business':b['name'],'start_cash':start_cash,'revenue':rev,'payroll':payroll_paid,'payroll_due':payroll,'opex':opex_paid,'interest':interest,'tax':tax_paid,'borrowed':borrowed,'profit':profit,'end_cash':int(b.get('cash',0)),'debt':int(b.get('debt',0))})
        weekly.update({'revenue':rev,'payroll':payroll_paid,'opex':opex_paid,'interest':interest,'tax':tax_paid,'profit':profit,'borrowed':borrowed})
    openings=build_openings(state['businesses'],year,week)
    state['version']=VERSION;state['last_processed_week']=key;state['updated_at']=utc_now();state.setdefault('cumulative',{})
    for k in ('revenue','payroll','opex','interest','tax','profit','borrowed'):state['cumulative'][k]=int(state['cumulative'].get(k,0))+int(weekly[k])
    state['last_week']={**dict(weekly),'world_week':key,'layoffs':total_layoffs,'bankruptcies':bankruptcies,'openings':len(openings)}
    write_json(STATE_PATH,state);save_finance(fin_ctx,world);build_summary(state)
    append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'business_economy_week_settled','revenue':weekly['revenue'],'payroll':weekly['payroll'],'profit':weekly['profit'],'business_tax':weekly['tax'],'layoffs':total_layoffs,'bankruptcies':bankruptcies,'openings':len(openings)})
    try:world.logger.info('[BUS171] Business Economy settled %s: revenue=$%d payroll=$%d profit=$%d layoffs=%d bankruptcies=%d openings=%d',key,weekly['revenue'],weekly['payroll'],weekly['profit'],total_layoffs,bankruptcies,len(openings))
    except Exception:pass


def build_summary(state:dict[str,Any]|None=None)->dict[str,Any]:
    state=state or read_json(STATE_PATH,{'businesses':{}});bs=list((state.get('businesses') or {}).values())
    active=[b for b in bs if isinstance(b,dict) and b.get('status')=='operating'];distressed=[b for b in active if int(b.get('distress_weeks',0))>=2];profitable=[b for b in active if int(b.get('profit_week',0))>0]
    bysector=defaultdict(lambda:{'businesses':0,'employees':0,'revenue':0,'profit':0,'debt':0})
    for b in active:
        s=bysector[str(b.get('sector') or 'Other')];s['businesses']+=1;s['employees']+=int(b.get('employees',0));s['revenue']+=int(b.get('revenue_week',0));s['profit']+=int(b.get('profit_week',0));s['debt']+=int(b.get('debt',0))
    top=sorted([{'name':b.get('name'),'sector':b.get('sector'),'entity_type':b.get('entity_type'),'owner':b.get('owner'),'employees':int(b.get('employees',0)),'revenue':int(b.get('revenue_week',0)),'profit':int(b.get('profit_week',0)),'cash':int(b.get('cash',0)),'debt':int(b.get('debt',0)),'estimated_value':int(b.get('estimated_value',0)),'distress_weeks':int(b.get('distress_weeks',0))} for b in active],key=lambda x:x['estimated_value'],reverse=True)[:25]
    last=state.get('last_week',{}) if isinstance(state.get('last_week'),dict) else {}
    out={'version':VERSION,'updated_at':utc_now(),'world_week':state.get('last_processed_week'),'businesses':len(bs),'operating_businesses':len(active),'profitable_businesses':len(profitable),'distressed_businesses':len(distressed),'bankrupt_businesses':sum(1 for b in bs if isinstance(b,dict) and b.get('status')=='bankrupt'),'citizen_owned_businesses':sum(1 for b in active if b.get('owner')),'jobs':sum(int(b.get('employees',0)) for b in active),'active_payroll_jobs':sum(int(b.get('active_payroll_employees',0)) for b in active),'revenue_week':int(last.get('revenue',0)),'payroll_week':int(last.get('payroll',0)),'operating_cost_week':int(last.get('opex',0)),'profit_week':int(last.get('profit',0)),'business_tax_week':int(last.get('tax',0)),'new_borrowing_week':int(last.get('borrowed',0)),'layoffs_week':int(last.get('layoffs',0)),'bankruptcies_week':int(last.get('bankruptcies',0)),'openings':read_json(OPENINGS_PATH,{'vacancies':[]}).get('vacancies',[]),'sector_economy':[{'sector':k,**v} for k,v in sorted(bysector.items())],'largest_businesses':top,'recent_events':tail_jsonl(EVENTS_PATH,50),'principles':{'businesses_have_finite_cash':True,'consumer_spending_funds_business_revenue':True,'employers_fund_payroll_clearing':True,'business_debt_is_persistent':True,'layoffs_and_bankruptcy_feed_career_economy':True,'protected_traits_never_used_for_business_decisions':True,'policy_values_are_fictional_2045_simulation_parameters':True}}
    write_json(SUMMARY_PATH,out);return out


def initialize()->dict[str,Any]:
    BUS.mkdir(parents=True,exist_ok=True)
    state=read_json(STATE_PATH,{'version':VERSION,'businesses':{},'last_processed_week':None,'cumulative':{}})
    if not isinstance(state,dict):state={'version':VERSION,'businesses':{},'last_processed_week':None,'cumulative':{}}
    state['version']=VERSION;state.setdefault('businesses',{});state.setdefault('cumulative',{});sync_business_registry(state)
    y,w=current_year_week()
    # No retroactive accounting on install. The first revenue/payroll/business-tax
    # settlement occurs only when Detroit advances to the next simulation week.
    if state.get('last_processed_week') is None:state['last_processed_week']=world_key(y,w)
    state['updated_at']=utc_now();write_json(STATE_PATH,state);build_openings(state['businesses'],y,w);return build_summary(state)


def business_context(name:str)->str:
    cdoc=career_doc();rec=(cdoc.get('citizens') or {}).get(name,{}) if isinstance(cdoc,dict) else {};org=str(rec.get('organization') or '') if isinstance(rec,dict) else ''
    state=read_json(STATE_PATH,{});b=next((x for x in (state.get('businesses') or {}).values() if isinstance(x,dict) and str(x.get('name'))==org),None) if isinstance(state,dict) else None
    if not b:return ''
    role='owner' if str(b.get('owner') or '')==name else 'employee'
    lines=[f'## Agentopia Business Economy v{VERSION}',f"- Employer: {b.get('name')} ({b.get('sector')}); you are an {role}.",f"- Employer condition: {b.get('status','unknown')}; revenue ${int(b.get('revenue_week',0)):,}/week; payroll ${int(b.get('payroll_week',0)):,}; profit ${int(b.get('profit_week',0)):,}; cash ${int(b.get('cash',0)):,}; debt ${int(b.get('debt',0)):,}."]
    if int(b.get('distress_weeks',0))>=2:lines.append('- Your employer is under financial pressure. Layoffs, restructuring, financing, reduced growth or closure are possible if conditions persist.')
    elif int(b.get('profit_week',0))>0:lines.append('- Your employer is currently profitable; expansion, investment and hiring may become possible if that continues.')
    if role=='owner':lines.append('- As an owner, business cash is not the same as personal cash. You may grow, borrow, repay debt, hire, restructure or eventually fail; the business has finite resources.')
    return '\n'.join(lines)


def install_career_opening_bridge()->None:
    try:import detroit_career_economy as career
    except Exception:return
    original=career.build_vacancies
    if getattr(original,'_agentopia_business_v171',False):return
    def business_aware_vacancies(year:int,week:int,count:int=60):
        base=original(year,week,count)
        extra_doc=read_json(OPENINGS_PATH,{'vacancies':[]});extra=extra_doc.get('vacancies',[]) if isinstance(extra_doc,dict) else []
        # Openings produced by the prior Business Economy settlement become real
        # Career Economy opportunities on the next career tick.
        existing={str(v.get('vacancy_id')) for v in base if isinstance(v,dict)}
        merged=list(base)+[v for v in extra if isinstance(v,dict) and str(v.get('vacancy_id')) not in existing]
        try:career.write_json(career.VACANCIES_PATH,{'updated_at':utc_now(),'world_year':year,'world_week':week,'vacancies':merged})
        except Exception:pass
        return merged
    business_aware_vacancies._agentopia_business_v171=True;career.build_vacancies=business_aware_vacancies


def apply_runtime_patches()->None:
    initialize();install_career_opening_bridge()
    from src.agents.data_manager import DataManager
    from src.world.world import World
    if not getattr(DataManager.character_prompt,'_agentopia_business_v171',False):
        original=DataManager.character_prompt
        def business_prompt(self):
            base=original(self)
            try:
                ctx=business_context(self.char);return str(base)+(('\n\n'+ctx) if ctx else '')
            except Exception:return base
        business_prompt._agentopia_business_v171=True;DataManager.character_prompt=business_prompt
    # Business settles AFTER Human Economy: households have already spent, so the
    # same money can be routed from settlement pools to real firms. Career/Base
    # payroll also already ran, allowing employers to replenish payroll clearing.
    if not getattr(World._before_week_start,'_agentopia_business_v171',False):
        original_before=World._before_week_start
        def business_before(self):
            result=original_before(self)
            try:process_week(self)
            except Exception as e:
                try:self.logger.warning('[BUS171] business settlement failed: %s',e)
                except Exception:pass
            return result
        business_before._agentopia_business_v171=True;World._before_week_start=business_before


def status()->None:
    s=initialize();print(f'Agentopia Detroit Business Economy v{VERSION}')
    print('Businesses:',s.get('businesses'),'Operating:',s.get('operating_businesses'),'Profitable:',s.get('profitable_businesses'),'Distressed:',s.get('distressed_businesses'),'Bankrupt:',s.get('bankrupt_businesses'))
    print('Citizen-owned:',s.get('citizen_owned_businesses'),'Jobs:',s.get('jobs'),'Openings:',len(s.get('openings',[])))
    print('Last week revenue:',s.get('revenue_week'),'Payroll:',s.get('payroll_week'),'Profit:',s.get('profit_week'),'Business tax:',s.get('business_tax_week'))
    print('State:',BUS)


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['init','status'],nargs='?',default='status');args=ap.parse_args()
    if args.command=='init':initialize()
    status()
