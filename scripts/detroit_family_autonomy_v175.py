#!/usr/bin/env python3
"""Deterministic, idempotent annual family milestones. Does not mutate people/economy."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path


def decide(people,events,year):
    from detroit_family_v175 import apply,status_map
    original=len(events)
    couples=set()
    for pid,person in sorted(people.items()):
        if not isinstance(person,dict) or not person.get('alive',True):continue
        for other in person.get('partners',[]):
            if other not in people or other==pid:continue
            partner=people[other]
            if not partner.get('alive',True):continue
            if pid not in partner.get('partners',[]):continue
            if min(int(person.get('age',0)),int(partner.get('age',0)))<18:continue
            couples.add(tuple(sorted((pid,other))))
    additions=[]
    for a,b in sorted(couples):
        key='|'.join((a,b))
        status=status_map(events)['relationship_status'].get(key,{}).get('status')
        if status is None:
            events,created=apply(events,people,'partner',a,b,year,'auto:verified-reciprocal-partnership')
            if created:additions.append(events[-1]); status='partnered'
        # Promotion to marriage is conservative and deterministic, and only for
        # explicit reciprocal adult couples recorded in at least a previous year.
        record=status_map(events)['relationship_status'].get(key,{})
        if status=='partnered' and int(record.get('year',year))<year:
            roll=int(hashlib.sha256(f'marry|{a}|{b}|{year}'.encode()).hexdigest()[:8],16)%100
            if roll<8:
                events,created=apply(events,people,'marry',a,b,year,'auto:annual-marriage-milestone')
                if created:additions.append(events[-1])
    return events,additions


def preview(root,year):
    from detroit_family_v175 import read,paths,validate_people
    p,e=paths(root);people=read(p,None);validate_people(people)
    doc=read(e,{'schema':1,'events':[]});assert doc.get('schema')==1
    _,new=decide(people,list(doc['events']),year)
    return {'year':year,'people':len(people),'proposed':new,'count':len(new)}


def run(root,year):
    # Import only after installation; process is serialized by lifecycle's
    # one-authority update entrypoint. Store only additive event registry.
    from detroit_family_v175 import read,paths,validate_people,atomic
    p,e=paths(root);people=read(p,None);validate_people(people)
    doc=read(e,{'schema':1,'events':[]});assert doc.get('schema')==1
    original=list(doc['events'])
    updated,new=decide(people,original,year)
    if new:atomic(e,{'schema':1,'events':updated})
    return {'year':year,'created':len(new),'total':len(updated)}

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['preview','status']);ap.add_argument('--root',default=str(Path.home()/'AI'/'Agentopia'));ap.add_argument('--year',type=int,required=True)
    a=ap.parse_args();print(json.dumps(preview(Path(a.root),a.year),indent=2))
