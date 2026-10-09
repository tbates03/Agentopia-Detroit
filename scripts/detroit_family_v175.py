#!/usr/bin/env python3
"""Agentopia family event register v1.7.5. Additive, explicit, no economic mutations."""
from __future__ import annotations
import argparse, hashlib, json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSION='1.7.5'
KINDS={'partner','marry','separate','divorce','care','household-plan','estate-plan'}

def read(p, default):
    if not p.exists(): return default
    return json.loads(p.read_text(encoding='utf-8'))

def atomic(p,obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+p.name+'.',dir=str(p.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            json.dump(obj,out,ensure_ascii=False,indent=2,sort_keys=True);out.write('\n');out.flush();os.fsync(out.fileno())
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def paths(root):
    world=root/'data'/'detroit_persistent'
    return world/'humanity'/'people.json',world/'humanity'/'family_v175'/'events.json'

def validate_people(people):
    if not isinstance(people,dict) or not people: raise ValueError('Missing or empty people dictionary')
    for k,v in people.items():
        if not isinstance(v,dict):raise ValueError('Invalid person: '+str(k))

def event_id(kind,a,b,year,note):
    payload=json.dumps([kind,a,b,year,note],ensure_ascii=False,separators=(',',':'))
    return 'FE-'+hashlib.sha256(payload.encode()).hexdigest()[:20].upper()

def status_map(events):
    couples={}; people_care={}; plans=[]
    for e in events:
        kind=e['type']; a=e['person_id'];b=e.get('other_id')
        if kind in {'partner','marry','separate','divorce'}:
            key='|'.join(sorted([a,b]))
            couples[key]={'person_ids':sorted([a,b]),'status':{'partner':'partnered','marry':'married','separate':'separated','divorce':'divorced'}[kind], 'event_id':e['id'],'year':e['year']}
        elif kind=='care':
            people_care.setdefault(b,[]).append({'carer_id':a,'event_id':e['id'],'year':e['year']})
        else:plans.append(e)
    return {'version':VERSION,'relationship_status':couples,'care_records':people_care,'nonfinancial_plans':plans,'event_count':len(events), 'economy_mutations':0}

def apply(events,people,kind,a,b,year,note):
    if kind not in KINDS:raise ValueError('Unsupported event')
    if a not in people:raise ValueError('Unknown primary person ID')
    if kind in {'partner','marry','separate','divorce','care'}:
        if not b or b not in people or b==a:raise ValueError('Other ID must be distinct existing person')
    elif b and b not in people:raise ValueError('Unknown other person ID')
    if kind in {'partner','marry','separate','divorce'}:
        if not people[a].get('alive',True) or not people[b].get('alive',True):raise ValueError('Relationship party not alive')
        if int(people[a].get('age',0)) < 18 or int(people[b].get('age',0)) < 18:raise ValueError('Both parties must be adults')
        state=status_map(events)['relationship_status'].get('|'.join(sorted([a,b])),{}).get('status')
        if kind=='marry' and state not in {'partnered','separated'}:raise ValueError('Marriage requires recorded partnership or separation')
        if kind in {'separate','divorce'} and state not in ({'partnered','married'} if kind=='separate' else {'married','separated'}):raise ValueError('No eligible relationship to change')
        if kind in {'partner','marry'}:
            for existing in status_map(events)['relationship_status'].values():
                if existing['status']=='married' and any(x in existing['person_ids'] for x in (a,b)) and sorted([a,b])!=existing['person_ids']:
                    raise ValueError('Already in a different recorded marriage')
    if kind=='care' and int(people[b].get('age',999))>=18:raise ValueError('Care target must be a minor for this event')
    id_=event_id(kind,*sorted([a,b]) if kind in {'partner','marry','separate','divorce'} else [a,b],year,note)
    if any(e['id']==id_ for e in events):return events,False
    event={'id':id_,'type':kind,'person_id':a,'other_id':b,'year':year,'note':note,'recorded_at':datetime.now(timezone.utc).isoformat()}
    return events+[event],True

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['status','preview','record','verify'])
    ap.add_argument('--root',default=str(Path.home()/'AI'/'Agentopia'))
    ap.add_argument('--type',choices=sorted(KINDS));ap.add_argument('--person');ap.add_argument('--other');ap.add_argument('--year',type=int);ap.add_argument('--note',default='')
    a=ap.parse_args();p,e=paths(Path(a.root).expanduser().resolve())
    try:
        people=read(p,None);validate_people(people)
        doc=read(e,{'schema':1,'events':[]})
        if not isinstance(doc,dict) or doc.get('schema')!=1 or not isinstance(doc.get('events'),list):raise ValueError('Invalid event registry')
        events=doc['events'];ids=[x['id'] for x in events]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate event IDs')
        if a.command=='verify':
            for x in events:
                if x['person_id'] not in people or (x.get('other_id') and x['other_id'] not in people):raise ValueError('Event refers to missing person: '+x['id'])
            print('PASS: event references valid; original people.json untouched');return 0
        if a.command=='status':
            out=status_map(events);out['people']=len(people);print(json.dumps(out,ensure_ascii=False,indent=2));return 0
        if not a.type or not a.person or not a.year or a.year<2000 or a.year>9999:raise ValueError('Provide --type, --person, and valid --year')
        new,changed=apply(events,people,a.type,a.person,a.other,a.year,a.note)
        print(json.dumps({'event_id':event_id(a.type,*(sorted([a.person,a.other]) if a.type in {'partner','marry','separate','divorce'} else [a.person,a.other]),a.year,a.note),'new':changed,'preview':a.command=='preview','type':a.type},indent=2))
        if a.command=='record' and changed:
            # only separate registry is mutated, not people, households, economy or engine
            atomic(e,{'schema':1,'events':new})
        return 0
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
