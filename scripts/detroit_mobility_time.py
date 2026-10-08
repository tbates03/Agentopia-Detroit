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
MOB = WORLD / 'mobility'
STATE_PATH = MOB / 'state.json'
SUMMARY_PATH = MOB / 'summary.json'
TRIPS_PATH = MOB / 'trips.ndjson'
EVENTS_PATH = MOB / 'events.ndjson'
VEHICLES_PATH = MOB / 'vehicles.json'
POLICY_PATH = MOB / 'policy.json'
HUMAN = WORLD / 'human_economy'
CAREER = WORLD / 'career'
EDU = WORLD / 'education'
HEALTH = WORLD / 'healthcare'
VERSION = '1.7.4'

DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']

# Abstract Detroit-zone coordinates used only for Agentopia travel-time simulation.
# They are not GIS coordinates and should not be interpreted as a real navigation map.
ZONES = {
    'Downtown': (0.0,0.0), 'Corktown':(-1.4,-0.2), 'Midtown':(0.1,2.0), 'New Center':(0.2,4.0),
    'Eastern Market':(1.6,1.2), 'Southwest Detroit':(-3.0,-1.0), 'Mexicantown':(-2.4,-0.8),
    'Woodbridge':(-1.2,2.1), 'North End':(0.9,5.0), 'Boston-Edison':(-0.4,6.0),
    'Palmer Woods':(0.0,9.1), 'Rosedale Park':(-7.0,8.0), 'Grandmont-Rosedale':(-6.4,7.0),
    'Brightmoor':(-8.4,6.0), 'Warrendale':(-8.0,1.1), 'Bagley':(-3.7,8.3),
    'University District':(-1.4,8.7), 'Jefferson-Chalmers':(7.5,1.0), 'Indian Village':(4.6,1.0),
    'East English Village':(7.1,4.5), 'West Village':(3.8,0.8), 'Lafayette Park':(1.2,0.2),
    'Riverfront':(0.5,-0.5), 'Michigan Central':(-1.7,0.0), 'TechTown':(0.0,2.7),
    'Detroit Metropolitan University':(0.2,2.6), 'Motor City Community College':(-1.0,3.0),
    'Detroit Trades Academy':(-3.0,2.0), 'Great Lakes Technology Institute':(0.0,2.8),
    'Detroit Health Sciences Institute':(0.4,2.2), 'Michigan Central Mobility Institute':(-1.8,0.0),
    'Motown Arts & Media Academy':(0.8,1.4), 'Detroit Civic Academy':(0.0,0.4),
    'Detroit Public Learning Network':(-0.2,4.2),
}

CORRIDORS = [
    ('M-1 / Woodward', lambda a,b: abs(a[0])<2 and abs(b[0])<2),
    ('I-75', lambda a,b: (a[1]-b[1])*(a[0]-b[0]) < 8),
    ('I-94', lambda a,b: max(a[1],b[1])>2.5 and abs(a[1]-b[1])<5),
    ('M-10 / Lodge', lambda a,b: min(a[0],b[0])<-1.5),
    ('Jefferson Avenue', lambda a,b: max(a[0],b[0])>3 and min(a[1],b[1])<3),
    ('Michigan Avenue', lambda a,b: min(a[0],b[0])<-1 and min(a[1],b[1])<2.5),
    ('Grand River Avenue', lambda a,b: min(a[0],b[0])<-3),
    ('Gratiot Avenue', lambda a,b: max(a[0],b[0])>2),
]

MODES = {
    'walk': {'speed':3.1,'wait':0,'parking':0,'road':False,'transit':False,'active':True},
    'bike': {'speed':10.5,'wait':1,'parking':2,'road':False,'transit':False,'active':True},
    'e_bike': {'speed':15.0,'wait':1,'parking':2,'road':False,'transit':False,'active':True},
    'ddot_bus': {'speed':14.0,'wait':9,'parking':0,'road':True,'transit':True,'active':False},
    'smart_bus': {'speed':16.0,'wait':11,'parking':0,'road':True,'transit':True,'active':False},
    'qline_rail': {'speed':18.0,'wait':7,'parking':0,'road':False,'transit':True,'active':False},
    'ridehail': {'speed':22.0,'wait':6,'parking':0,'road':True,'transit':False,'active':False},
    'private_car': {'speed':24.0,'wait':0,'parking':7,'road':True,'transit':False,'active':False},
    'private_ev': {'speed':24.0,'wait':0,'parking':7,'road':True,'transit':False,'active':False},
    'autonomous_ev': {'speed':23.0,'wait':2,'parking':3,'road':True,'transit':False,'active':False},
}

INSTITUTION_ZONE = {
    'detroit_public_learning':'Detroit Public Learning Network',
    'motor_city_community_college':'Motor City Community College',
    'detroit_trades_academy':'Detroit Trades Academy',
    'great_lakes_technology':'Great Lakes Technology Institute',
    'detroit_metropolitan_university':'Detroit Metropolitan University',
    'detroit_health_sciences':'Detroit Health Sciences Institute',
    'michigan_central_mobility':'Michigan Central Mobility Institute',
    'motown_arts_media':'Motown Arts & Media Academy',
    'detroit_civic_academy':'Detroit Civic Academy',
}

SECTOR_ZONE = {
    'Medicine & Health':'Midtown', 'AI, Software & Technology':'TechTown', 'Cybersecurity & Intelligence':'Downtown',
    'Engineering & Manufacturing':'Michigan Central', 'Mobility, Robotics & Infrastructure':'Michigan Central',
    'Law, Government & Public Safety':'Downtown', 'Science & Research':'Midtown', 'Education':'New Center',
    'Creative, Media & Entertainment':'Midtown', 'Construction & Skilled Trades':'Southwest Detroit',
    'Business & Operations':'Downtown', 'Community, Hospitality & Everyday Economy':'Eastern Market',
    'Executive, Ownership & Finance':'Downtown',
}

POLICY = {
    'version':VERSION,
    'clock_model':'phase-derived 7-day city clock layered on Agentopia weekly phases',
    'transport_finance_rule':'Human Economy owns citizen transport debits. Mobility allocates that already-paid budget to trips and modes; it does not charge citizens again.',
    'max_commute_minutes_soft':90,
    'incident_probability_per_trip':0.0008,
    'remote_eligible_sectors':['AI, Software & Technology','Cybersecurity & Intelligence','Business & Operations','Creative, Media & Entertainment','Science & Research'],
    'protected_traits_never_used_for_mobility_access':True,
}


def utc_now()->str:return datetime.now(timezone.utc).isoformat()

def read_json(path:Path,default:Any)->Any:
    try:return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    except Exception:return default

def write_json(path:Path,obj:Any)->None:
    path.parent.mkdir(parents=True,exist_ok=True);t=path.with_suffix(path.suffix+'.tmp');t.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(path)

def append_jsonl(path:Path,obj:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')

def tail_jsonl(path:Path,n:int)->list[dict[str,Any]]:
    if not path.exists():return []
    out=[]
    try:
        lines=path.read_text(encoding='utf-8',errors='replace').splitlines()[-n:]
        for line in lines:
            try:
                x=json.loads(line)
                if isinstance(x,dict):out.append(x)
            except Exception:pass
    except Exception:pass
    return out

def stable_rng(*parts:Any)->random.Random:
    h=hashlib.sha256('|'.join(map(str,parts)).encode()).hexdigest();return random.Random(int(h[:16],16))

def latest_profile(name:str)->dict[str,Any]:
    pdir=WORLD/'persona'/name/'profile';files=sorted(pdir.glob('year=*.json')) if pdir.exists() else []
    return read_json(files[-1],{}) if files else {}

def checkpoint_time()->tuple[int,int,str,int,str]:
    cp=read_json(WORLD/'checkpoint.json',{});raw=str(cp.get('current_time') or cp.get('time') or '')
    m=re.search(r'Y(\d+)-W(\d+)-([A-Za-z_]+)(?:-S(\d+))?',raw)
    if m:return int(m.group(1)),int(m.group(2)),m.group(3).lower(),int(m.group(4) or 0),raw
    m=re.search(r'Y(\d+)-W(\d+)',raw)
    return (int(m.group(1)),int(m.group(2)),'plan',0,raw) if m else (2045,1,'plan',0,raw)

def week_key(year:int,week:int)->str:return f'Y{year}-W{week:02d}'

def phase_clock(phase:str,slot:int=0)->dict[str,Any]:
    p=phase.lower().replace('-','_')
    if p=='before_contact':return {'day':'Monday','time':'06:30','hour':6.5,'label':'Mon 6:30 AM'}
    if p=='contact':
        d=DAYS[max(0,min(4,slot-1))];return {'day':d,'time':'17:30','hour':17.5,'label':f'{d[:3]} 5:30 PM'}
    if p in {'after_contact','aftercontact'}:return {'day':'Friday','time':'21:00','hour':21.0,'label':'Fri 9:00 PM'}
    if p=='activity':return {'day':'Saturday','time':'14:00','hour':14.0,'label':'Sat 2:00 PM'}
    if p=='review':return {'day':'Sunday','time':'17:00','hour':17.0,'label':'Sun 5:00 PM'}
    return {'day':'Sunday','time':'20:00','hour':20.0,'label':'Sun 8:00 PM'}

def zone_xy(name:str)->tuple[float,float]:
    if name in ZONES:return ZONES[name]
    keys=sorted(ZONES);return ZONES[keys[int(hashlib.sha1(name.encode()).hexdigest()[:8],16)%len(keys)]]

def distance_miles(a:str,b:str)->float:
    ax,ay=zone_xy(a);bx,by=zone_xy(b);return max(0.2,math.hypot(ax-bx,ay-by)*0.92)

def corridor_for(a:str,b:str)->str:
    aa=zone_xy(a);bb=zone_xy(b)
    for name,fn in CORRIDORS:
        try:
            if fn(aa,bb):return name
        except Exception:pass
    return 'Detroit surface streets'

def weather_for(year:int,week:int)->dict[str,Any]:
    rng=stable_rng('detroit-weather',year,week);w=(week-1)%52+1
    if w<=9 or w>=48:
        kind=rng.choices(['cold_clear','snow','winter_mix'],[0.54,0.31,0.15])[0];impact={'cold_clear':1.03,'snow':1.28,'winter_mix':1.35}[kind]
    elif 10<=w<=21:
        kind=rng.choices(['mild','rain','storm'],[0.58,0.32,0.10])[0];impact={'mild':1.0,'rain':1.12,'storm':1.24}[kind]
    elif 22<=w<=38:
        kind=rng.choices(['clear','hot','storm'],[0.62,0.23,0.15])[0];impact={'clear':1.0,'hot':1.03,'storm':1.20}[kind]
    else:
        kind=rng.choices(['clear','rain','wind'],[0.58,0.30,0.12])[0];impact={'clear':1.0,'rain':1.11,'wind':1.08}[kind]
    return {'condition':kind,'travel_time_factor':impact}

def household_maps()->tuple[dict[str,Any],dict[str,Any],dict[str,str]]:
    hh=read_json(HUMAN/'households.json',{'households':{}}).get('households',{})
    housing=read_json(HUMAN/'housing.json',{'units':{}}).get('units',{})
    byname={}
    for hid,rec in hh.items():
        if not isinstance(rec,dict):continue
        for n in rec.get('members',[]):byname[str(n)]=str(hid)
    return hh if isinstance(hh,dict) else {},housing if isinstance(housing,dict) else {},byname

def home_zone(name:str,hh:dict[str,Any],housing:dict[str,Any],byname:dict[str,str])->str:
    hid=byname.get(name);rec=hh.get(hid,{}) if hid else {};pid=rec.get('property_id') if isinstance(rec,dict) else None
    unit=housing.get(pid,{}) if pid else {}
    z=str(unit.get('neighborhood') or '')
    if z:return z
    common=['Midtown','Corktown','New Center','Eastern Market','Southwest Detroit','Rosedale Park','Jefferson-Chalmers','Warrendale']
    return common[int(hashlib.sha1(name.encode()).hexdigest()[:8],16)%len(common)]

def work_zone(name:str,career:dict[str,Any])->str:
    rec=career.get(name,{}) if isinstance(career,dict) else {};org=str(rec.get('organization') or '')
    low=org.lower()
    if 'guardian' in low:return 'Downtown'
    if 'obsidian' in low:return 'Michigan Central'
    if 'health' in low or 'hospital' in low:return 'Midtown'
    if 'university' in low or 'college' in low:return 'Midtown'
    if 'restaurant' in low or 'market' in low:return 'Eastern Market'
    if 'manufactur' in low or 'auto' in low:return 'Michigan Central'
    sec=str(rec.get('sector') or '')
    return SECTOR_ZONE.get(sec,'Downtown')

def school_zone(edu_rec:dict[str,Any])->str|None:
    e=edu_rec.get('active_enrollment') if isinstance(edu_rec,dict) else None
    if not isinstance(e,dict):return None
    iid=str(e.get('institution') or e.get('institution_id') or '')
    if iid in INSTITUTION_ZONE:return INSTITUTION_ZONE[iid]
    title=str(e.get('title') or '').lower()
    if 'k-12' in title:return 'Detroit Public Learning Network'
    return 'Midtown'

def age_for(name:str,health:dict[str,Any],year:int)->int:
    r=health.get(name,{}) if isinstance(health,dict) else {}
    if r.get('age') is not None:
        try:return int(r.get('age'))
        except Exception:pass
    p=latest_profile(name);by=p.get('birth_year')
    try:return max(0,year-int(by))
    except Exception:return 35

def choose_mode(name:str,home:str,dest:str,eclass:str,age:int,health_rec:dict[str,Any],career_rec:dict[str,Any],vehicles:list[dict[str,Any]],year:int,week:int)->str:
    d=distance_miles(home,dest);rng=stable_rng(name,year,week,'mode');physical=int(health_rec.get('physical_health',70) or 70)
    if d<=0.8 and physical>=45:return 'walk'
    if d<=2.4 and physical>=55 and rng.random()<0.38:return 'e_bike' if rng.random()<0.65 else 'bike'
    if age<16:return 'ddot_bus' if d>1.2 else 'walk'
    if vehicles:
        vt=str(vehicles[0].get('type') or '')
        if vt=='autonomous_ev':return 'autonomous_ev'
        if vt in {'compact_ev','utility_ev'}:return 'private_ev'
        return 'private_car'
    if home in {'Downtown','Midtown','New Center'} and dest in {'Downtown','Midtown','New Center'} and rng.random()<0.55:return 'qline_rail'
    if eclass in {'affluent','wealthy','upper-middle'} and rng.random()<0.35:return 'ridehail'
    return 'ddot_bus' if rng.random()<0.78 else 'smart_bus'

def vehicles_for_households(hh:dict[str,Any],housing:dict[str,Any],year:int,week:int)->dict[str,list[dict[str,Any]]]:
    old=read_json(VEHICLES_PATH,{'households':{}});out=old.get('households',{}) if isinstance(old,dict) else {}
    if not isinstance(out,dict):out={}
    for hid,rec in hh.items():
        if not isinstance(rec,dict):continue
        current=out.get(hid)
        if isinstance(current,list):continue
        cls=str(rec.get('economic_class') or 'middle');size=max(1,int(rec.get('household_size',1) or 1));rng=stable_rng(hid,'vehicles')
        prob={'hardship':0.18,'working':0.46,'middle':0.70,'upper-middle':0.88,'affluent':0.96,'wealthy':0.99}.get(cls,0.65)
        count=0
        if rng.random()<prob:count=1
        if size>=3 and cls in {'middle','upper-middle','affluent','wealthy'} and rng.random()<0.38:count+=1
        cars=[]
        for i in range(count):
            r=rng.random()
            if r<0.18:typ='autonomous_ev'
            elif r<0.70:typ='compact_ev'
            elif r<0.87:typ='utility_ev'
            else:typ='used_hybrid'
            cars.append({'vehicle_id':f'{hid}-V{i+1}','type':typ,'model_year':rng.randint(2033,2045),'condition':rng.randint(62,96),'charging':'home_or_neighborhood' if 'ev' in typ else 'fuel','created_version':VERSION})
        out[hid]=cars
    write_json(VEHICLES_PATH,{'version':VERSION,'updated_at':utc_now(),'households':out});return out

def transport_paid_for_week(key:str)->dict[str,int]:
    out=Counter()
    path=HUMAN/'ledger.ndjson'
    if not path.exists():return {}
    try:
        for line in path.read_text(encoding='utf-8',errors='replace').splitlines()[-5000:]:
            try:r=json.loads(line)
            except Exception:continue
            if str(r.get('world_week'))==key and str(r.get('category'))=='transport':out[str(r.get('citizen'))]+=int(r.get('paid',0) or 0)
    except Exception:pass
    return dict(out)

def trip_minutes(mode:str,distance:float,peak:bool,weather:float,congestion:float)->int:
    meta=MODES[mode];drive=60*distance/max(1.0,float(meta['speed']))
    factor=weather*(congestion if meta['road'] else (1.04 if meta['transit'] else 1.0))*(1.18 if peak else 1.0)
    return max(3,int(round(drive*factor+float(meta['wait'])+float(meta['parking']))))

def make_trip(name:str,day:str,purpose:str,origin:str,dest:str,mode:str,depart:str,year:int,week:int,weather:dict[str,Any],congestion:float)->dict[str,Any]:
    d=round(distance_miles(origin,dest),1);hh=int(depart.split(':')[0]);peak=hh in {7,8,16,17,18};mins=trip_minutes(mode,d,peak,float(weather['travel_time_factor']),congestion)
    return {'citizen':name,'day':day,'purpose':purpose,'origin':origin,'destination':dest,'mode':mode,'depart':depart,'distance_miles':d,'minutes':mins,'corridor':corridor_for(origin,dest),'peak':peak}

def schedule_for(name:str,home:str,dest:str,school:str|None,mode:str,career_rec:dict[str,Any],edu_rec:dict[str,Any],year:int,week:int,weather:dict[str,Any],congestion:float)->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    rng=stable_rng(name,year,week,'schedule');sector=str(career_rec.get('sector') or '');status=str(career_rec.get('status') or 'employed');title=str(career_rec.get('current_title') or '')
    remote_ok=sector in POLICY['remote_eligible_sectors'];remote_days=set(rng.sample(DAYS[:5],k=2 if remote_ok and rng.random()<0.55 else (1 if remote_ok and rng.random()<0.60 else 0)))
    shift='day'
    if sector in {'Medicine & Health','Law, Government & Public Safety','Community, Hospitality & Everyday Economy'} and rng.random()<0.24:shift=rng.choice(['evening','night'])
    days=[];trips=[]
    main_dest=school or dest
    for day in DAYS:
        weekend=day in {'Saturday','Sunday'};blocks=[]
        if weekend:
            blocks=[{'start':'00:00','end':'08:00','activity':'sleep','location':home},{'start':'08:00','end':'11:00','activity':'home / personal','location':home},{'start':'11:00','end':'17:00','activity':'errands / social / recreation','location':home},{'start':'17:00','end':'23:59','activity':'family / leisure','location':home}]
            if day=='Saturday' and rng.random()<0.62:
                leisure='Downtown' if rng.random()<0.5 else 'Eastern Market';trips.append(make_trip(name,day,'leisure',home,leisure,mode,'11:00',year,week,weather,congestion));trips.append(make_trip(name,day,'return',leisure,home,mode,'16:00',year,week,weather,congestion))
        elif status in {'retired','unemployed'} and not school:
            blocks=[{'start':'00:00','end':'07:30','activity':'sleep','location':home},{'start':'07:30','end':'12:00','activity':'home / job search / personal','location':home},{'start':'12:00','end':'17:30','activity':'errands / appointments / community','location':home},{'start':'17:30','end':'23:59','activity':'home / social','location':home}]
            if rng.random()<0.45:
                err='Eastern Market';trips.append(make_trip(name,day,'errand',home,err,mode,'12:30',year,week,weather,congestion));trips.append(make_trip(name,day,'return',err,home,mode,'14:00',year,week,weather,congestion))
        elif day in remote_days and not school:
            blocks=[{'start':'00:00','end':'06:45','activity':'sleep','location':home},{'start':'06:45','end':'08:00','activity':'morning routine','location':home},{'start':'08:00','end':'17:00','activity':'remote work','location':home},{'start':'17:00','end':'23:59','activity':'home / errands / social','location':home}]
        else:
            if shift=='night' and not school:
                out='18:30';back='06:30';work_start='19:30';work_end='06:00'
                blocks=[{'start':'00:00','end':'06:00','activity':'work','location':main_dest},{'start':'06:00','end':'14:00','activity':'sleep / recovery','location':home},{'start':'14:00','end':'18:30','activity':'home / personal','location':home},{'start':'19:30','end':'23:59','activity':'work','location':main_dest}]
            elif shift=='evening' and not school:
                out='13:00';back='22:15';work_start='14:00';work_end='22:00'
                blocks=[{'start':'00:00','end':'08:00','activity':'sleep','location':home},{'start':'08:00','end':'13:00','activity':'home / personal','location':home},{'start':'14:00','end':'22:00','activity':'work','location':main_dest},{'start':'22:45','end':'23:59','activity':'home','location':home}]
            else:
                out='07:30';back='17:15';work_start='08:30';work_end='17:00'
                activity='school / training' if school else 'work'
                blocks=[{'start':'00:00','end':'06:30','activity':'sleep','location':home},{'start':'06:30','end':'07:30','activity':'morning routine','location':home},{'start':work_start,'end':work_end,'activity':activity,'location':main_dest},{'start':'18:15','end':'23:59','activity':'home / family / social / learning','location':home}]
            trips.append(make_trip(name,day,'commute_out',home,main_dest,mode,out,year,week,weather,congestion));trips.append(make_trip(name,day,'commute_home',main_dest,home,mode,back,year,week,weather,congestion))
        days.append({'day':day,'blocks':blocks,'remote':day in remote_days,'shift':shift})
    return days,trips

def build_summary(state:dict[str,Any]|None=None)->dict[str,Any]:
    state=state or read_json(STATE_PATH,{})
    people=state.get('citizens',{}) if isinstance(state,dict) else {};vals=[v for v in people.values() if isinstance(v,dict)] if isinstance(people,dict) else []
    trips=[t for v in vals for t in v.get('trips',[]) if isinstance(t,dict)]
    commute=[int(t.get('minutes',0)) for t in trips if str(t.get('purpose','')).startswith('commute')]
    modes=Counter(str(t.get('mode')) for t in trips);corridors=Counter(str(t.get('corridor')) for t in trips)
    road=sum(v for k,v in modes.items() if MODES.get(k,{}).get('road'));transit=sum(v for k,v in modes.items() if MODES.get(k,{}).get('transit'));active=sum(v for k,v in modes.items() if MODES.get(k,{}).get('active'))
    hhveh=read_json(VEHICLES_PATH,{'households':{}}).get('households',{});vehicles=[x for arr in hhveh.values() if isinstance(arr,list) for x in arr if isinstance(x,dict)] if isinstance(hhveh,dict) else []
    ev=sum(1 for v in vehicles if 'ev' in str(v.get('type')));av=sum(1 for v in vehicles if str(v.get('type'))=='autonomous_ev')
    y,w,phase,slot,raw=checkpoint_time();clock=phase_clock(phase,slot);last=state.get('last_week',{}) if isinstance(state,dict) else {}
    sample=sorted([{'name':v.get('name'),'home':v.get('home'),'destination':v.get('primary_destination'),'mode':v.get('primary_mode'),'avg_commute_minutes':v.get('avg_commute_minutes'),'weekly_miles':v.get('weekly_miles'),'transport_budget':v.get('transport_budget'),'vehicle':v.get('vehicle_label'),'shift':v.get('shift')} for v in vals],key=lambda x:int(x.get('avg_commute_minutes') or 0),reverse=True)[:40]
    out={
        'version':VERSION,'updated_at':utc_now(),'world_week':state.get('last_processed_week'),'city_clock':clock,'engine_time':raw,'phase':phase,'slot':slot,
        'citizens_tracked':len(vals),'trips_week':len(trips),'avg_commute_minutes':round(mean(commute),1) if commute else 0,'median_commute_minutes':round(median(commute),1) if commute else 0,'long_commutes':sum(1 for v in vals if int(v.get('avg_commute_minutes',0))>45),
        'weekly_miles':round(sum(float(v.get('weekly_miles',0)) for v in vals),1),'transport_spend_week':int(last.get('transport_spend',0)),'congestion_index':last.get('congestion_index',1.0),'weather':last.get('weather',{}),'incidents_week':int(last.get('incidents',0)),'delay_minutes_week':int(last.get('delay_minutes',0)),
        'vehicle_households':sum(1 for arr in hhveh.values() if isinstance(arr,list) and arr),'vehicle_count':len(vehicles),'ev_share_pct':round(100*ev/max(1,len(vehicles)),1),'autonomous_share_pct':round(100*av/max(1,len(vehicles)),1),
        'mode_share':dict(modes),'transit_share_pct':round(100*transit/max(1,len(trips)),1),'active_transport_share_pct':round(100*active/max(1,len(trips)),1),'road_trip_share_pct':round(100*road/max(1,len(trips)),1),
        'busiest_corridors':[{'corridor':k,'trips':v} for k,v in corridors.most_common(10)],'citizen_mobility':sample,'recent_events':tail_jsonl(EVENTS_PATH,40),'trip_samples':trips[:120],
        'principles':{'citizens_have_24_hour_weekly_schedules':True,'distance_and_commute_time_matter':True,'human_economy_owns_transport_debits':True,'no_duplicate_transport_charges':True,'vehicles_persist_by_household':True,'protected_traits_never_used_for_access':True,'zone_coordinates_are_simulation_only_not_navigation':True}
    }
    write_json(SUMMARY_PATH,out);return out

def initialize()->dict[str,Any]:
    MOB.mkdir(parents=True,exist_ok=True);write_json(POLICY_PATH,POLICY)
    y,w,phase,slot,raw=checkpoint_time();key=week_key(y,w)
    hh,housing,byname=household_maps();veh=vehicles_for_households(hh,housing,y,w)
    state=read_json(STATE_PATH,{'version':VERSION,'last_processed_week':None,'citizens':{}})
    if not isinstance(state,dict):state={'version':VERSION,'last_processed_week':None,'citizens':{}}
    state['version']=VERSION;state.setdefault('citizens',{})
    # Seed this current week for visibility, but mark it processed so restart/install cannot advance twice.
    if state.get('last_processed_week')!=key:generate_week(state,y,w,hh,housing,byname,veh,protect_current=True)
    state['last_processed_week']=key;state['updated_at']=utc_now();write_json(STATE_PATH,state);return build_summary(state)

def generate_week(state:dict[str,Any],year:int,week:int,hh:dict[str,Any],housing:dict[str,Any],byname:dict[str,str],veh:dict[str,list[dict[str,Any]]],protect_current:bool=False)->None:
    key=week_key(year,week);career=read_json(CAREER/'state.json',{'citizens':{}}).get('citizens',{});edu=read_json(EDU/'state.json',{'citizens':{}}).get('citizens',{});health=read_json(HEALTH/'state.json',{'citizens':{}}).get('citizens',{})
    paid=transport_paid_for_week(key);weather=weather_for(year,week);base_rng=stable_rng('congestion',year,week);congestion=round(base_rng.uniform(1.05,1.28)*(float(weather['travel_time_factor'])**0.35),3)
    incident_count=0;delay_total=0;corridor_load=Counter()
    names=sorted({p.name for p in (WORLD/'persona').iterdir() if p.is_dir()}) if (WORLD/'persona').exists() else []
    for name in names:
        cr=career.get(name,{}) if isinstance(career,dict) else {};er=edu.get(name,{}) if isinstance(edu,dict) else {};hr=health.get(name,{}) if isinstance(health,dict) else {};hid=byname.get(name,'')
        home=home_zone(name,hh,housing,byname);dest=work_zone(name,career);school=school_zone(er);age=age_for(name,health,year);hrec=hh.get(hid,{}) if hid else {};eclass=str(hrec.get('economic_class') or 'middle');cars=veh.get(hid,[]) if hid else []
        mode=choose_mode(name,home,school or dest,eclass,age,hr,cr,cars,year,week);days,trips=schedule_for(name,home,dest,school,mode,cr,er,year,week,weather,congestion)
        rng=stable_rng(name,year,week,'incidents');incidents=[]
        for t in trips:
            corridor_load[str(t.get('corridor'))]+=1;delay=max(0,int(t.get('minutes',0))-int(round(60*float(t.get('distance_miles',0))/max(1.0,float(MODES.get(mode,{}).get('speed',20))))));delay_total+=delay
            risk=POLICY['incident_probability_per_trip']*(1.5 if weather['condition'] in {'snow','winter_mix','storm'} else 1.0)*(1.20 if MODES.get(mode,{}).get('road') else 0.65)
            if rng.random()<risk:
                incident={'event':'mobility_incident','world_week':key,'citizen':name,'day':t.get('day'),'mode':mode,'corridor':t.get('corridor'),'severity':rng.choices(['minor_delay','minor_collision','injury_possible'],[0.72,0.23,0.05])[0],'extra_delay_minutes':rng.randint(12,55)};incidents.append(incident);incident_count+=1;append_jsonl(EVENTS_PATH,{'time':utc_now(),**incident})
            if not protect_current:append_jsonl(TRIPS_PATH,{'time':utc_now(),'world_week':key,**t})
        comm=[int(t['minutes']) for t in trips if str(t.get('purpose')).startswith('commute')];weekly_miles=round(sum(float(t.get('distance_miles',0)) for t in trips),1)
        rec={'name':name,'household_id':hid,'home':home,'primary_destination':school or dest,'work_destination':dest,'school_destination':school,'primary_mode':mode,'vehicle_label':(cars[0].get('type') if cars else 'none'),'age':age,'economic_class':eclass,'schedule':days,'trips':trips,'weekly_miles':weekly_miles,'avg_commute_minutes':round(mean(comm),1) if comm else 0,'transport_budget':int(paid.get(name,0)),'incidents':incidents,'shift':next((d.get('shift') for d in days if d.get('day')=='Monday'),'day'),'updated_week':key}
        state['citizens'][name]=rec
    state['last_week']={'world_week':key,'weather':weather,'congestion_index':congestion,'transport_spend':sum(paid.values()),'incidents':incident_count,'delay_minutes':delay_total,'corridors':dict(corridor_load),'protected_seed':bool(protect_current)}
    if not protect_current:append_jsonl(EVENTS_PATH,{'time':utc_now(),'world_week':key,'event':'mobility_week_generated','citizens':len(names),'trips':sum(len(r.get('trips',[])) for r in state['citizens'].values()),'congestion_index':congestion,'weather':weather['condition'],'incidents':incident_count})

def week_start(world:Any)->None:
    t=world.clock.get_time();year=int(getattr(t,'year',2045));week=int(getattr(t,'week',1));key=week_key(year,week)
    state=read_json(STATE_PATH,{'version':VERSION,'last_processed_week':None,'citizens':{}})
    if state.get('last_processed_week')==key:build_summary(state);return
    hh,housing,byname=household_maps();veh=vehicles_for_households(hh,housing,year,week);generate_week(state,year,week,hh,housing,byname,veh,protect_current=False)
    state['version']=VERSION;state['last_processed_week']=key;state['updated_at']=utc_now();write_json(STATE_PATH,state);build_summary(state)
    try:world.logger.info('[MOB174] Mobility & Time generated %s: citizens=%d trips=%d',key,len(state.get('citizens',{})),sum(len(r.get('trips',[])) for r in state.get('citizens',{}).values()))
    except Exception:pass

def mobility_context(name:str)->str:
    s=read_json(STATE_PATH,{});r=(s.get('citizens') or {}).get(name,{}) if isinstance(s,dict) else {}
    if not r:return ''
    y,w,phase,slot,raw=checkpoint_time();clock=phase_clock(phase,slot);incs=r.get('incidents') or []
    lines=[
        f'## Agentopia Mobility & Time v{VERSION}',
        f"- Phase-derived Detroit city clock: {clock['label']} during {phase}{(' slot '+str(slot)) if slot else ''}. This clock maps Agentopia weekly phases into a human-readable 7-day routine; it is not wall-clock time.",
        f"- Home: {r.get('home','Detroit')}; primary destination: {r.get('primary_destination','Detroit')}; regular mode: {str(r.get('primary_mode','unknown')).replace('_',' ')}.",
        f"- Typical one-way commute: {r.get('avg_commute_minutes',0)} minutes; modeled weekly travel: {r.get('weekly_miles',0)} miles; household vehicle access: {str(r.get('vehicle_label','none')).replace('_',' ')}.",
        f"- Human Economy already paid/allocated about ${int(r.get('transport_budget',0)):,} for your latest weekly transport obligation. Mobility must not charge that amount again.",
        '- Distance and travel time are real constraints. Consider commute time, traffic, transit availability, weather, schedule conflicts and fatigue when deciding where to go or what commitments to accept.',
    ]
    if incs:lines.append(f"- Recent mobility issue: {incs[-1].get('severity','incident')} on {incs[-1].get('corridor','Detroit route')}. Treat it as lived experience, not as a medical diagnosis.")
    return '\n'.join(lines)

def apply_runtime_patches()->None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.world.world import World
    if not getattr(DataManager.character_prompt,'_agentopia_mobility_v174',False):
        original=DataManager.character_prompt
        def mobility_prompt(self):
            base=original(self)
            try:return str(base)+'\n\n'+mobility_context(self.char)
            except Exception:return base
        mobility_prompt._agentopia_mobility_v174=True;DataManager.character_prompt=mobility_prompt
    if not getattr(World._before_week_start,'_agentopia_mobility_v174',False):
        original_before=World._before_week_start
        def mobility_before(self):
            original_before(self)
            try:week_start(self)
            except Exception as e:
                try:self.logger.warning('[MOB174] mobility week failed: %s',e)
                except Exception:pass
        mobility_before._agentopia_mobility_v174=True;World._before_week_start=mobility_before

def status()->None:
    s=initialize();print(f'Agentopia Detroit Mobility & Time v{VERSION}')
    print('Citizens:',s.get('citizens_tracked'),'Trips/week:',s.get('trips_week'),'Average commute:',s.get('avg_commute_minutes'),'minutes')
    print('Vehicle households:',s.get('vehicle_households'),'Vehicles:',s.get('vehicle_count'),'EV share:',str(s.get('ev_share_pct'))+'%','AV share:',str(s.get('autonomous_share_pct'))+'%')
    print('Transit share:',str(s.get('transit_share_pct'))+'%','Active share:',str(s.get('active_transport_share_pct'))+'%','Congestion:',s.get('congestion_index'))
    print('Phase city clock:',(s.get('city_clock') or {}).get('label'),'Weather:',(s.get('weather') or {}).get('condition'),'Incidents:',s.get('incidents_week'))
    print('Transport finance: Human Economy owns citizen debits; v1.7.4 does not double-charge transport.')

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['init','status'],nargs='?',default='status');args=ap.parse_args()
    if args.command=='init':initialize()
    status()
