#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(os.environ.get('AGENTOPIA_HOME', str(Path.home() / 'AI' / 'Agentopia'))).expanduser().resolve()
WORLD = ROOT / 'data' / 'detroit_persistent'
ECON = WORLD / 'human_economy'
STATE_PATH = ECON / 'state.json'
HOUSEHOLDS_PATH = ECON / 'households.json'
HOUSING_PATH = ECON / 'housing.json'
MARKET_PATH = ECON / 'market.json'
POLICY_PATH = ECON / 'policy.json'
SUMMARY_PATH = ECON / 'summary.json'
LEDGER_PATH = ECON / 'ledger.ndjson'
EVENTS_PATH = ECON / 'events.ndjson'
VERSION = '1.8.0'

# Fictional 2045 Agentopia policy. Structure is Detroit/Michigan-like, but these
# are simulation parameters, not a representation of future tax law.
DEFAULT_POLICY = {
    'version': VERSION,
    'jurisdiction': 'Agentopia Detroit 2045',
    'simulation_only': True,
    'taxes': {
        'city_income_rate': 0.024,
        'state_income_rate': 0.0425,
        'payroll_rate': 0.015,
        'federal_effective_brackets': [
            [325, 0.00], [500, 0.03], [700, 0.06], [1000, 0.09],
            [1500, 0.12], [2500, 0.16], [10**9, 0.20],
        ],
    },
    'weekly_cost_baseline': {
        'food_baby': 24, 'food_child': 34, 'food_teen': 45,
        'food_adult': 55, 'food_senior': 50,
        'utilities_base': 34, 'utilities_per_person': 8,
        'transport_per_adult': 22, 'health_per_adult': 18,
        'health_per_child': 9, 'communications_base': 18,
        'communications_per_person': 5,
    },
    'safety_net': {'enabled': True, 'max_weekly_household_aid': 120, 'cash_floor': 60},
    'housing': {'affordability_target': 0.28, 'hardship_move_after_weeks': 4},
}

NEIGHBORHOODS = [
    ('Downtown', 1.45), ('Midtown', 1.35), ('Corktown', 1.30), ('New Center', 1.18),
    ('Eastern Market', 1.14), ('Southwest Detroit', 0.86), ('Woodbridge', 1.15),
    ('North End', 0.80), ('Boston-Edison', 1.50), ('Palmer Woods', 1.65),
    ('Rosedale Park', 1.05), ('Grandmont-Rosedale', 1.00), ('Jefferson-Chalmers', 0.90),
    ('East English Village', 0.95), ('Indian Village', 1.55), ('West Village', 1.25),
    ('Bagley', 0.90), ('Brightmoor', 0.66), ('Warrendale', 0.80), ('Islandview', 0.96),
]

UNIT_TYPES = [
    ('Studio Apartment', 0, 78), ('One-Bedroom Apartment', 1, 98),
    ('Two-Bedroom Apartment', 2, 128), ('Loft', 1, 122),
    ('Townhouse', 2, 155), ('Detroit Bungalow', 3, 166),
    ('Duplex Unit', 3, 172), ('Family House', 4, 195),
]

PRICE_CATEGORIES = ['housing','groceries','utilities','transport','healthcare','insurance','communications','discretionary']
DESTINATION = {
    'taxes': 'institution:dcb:municipal_treasury',
    'housing': 'institution:merchant:merchant_settlement',
    'utilities': 'institution:dcb:utility_revenue',
    'food': 'institution:merchant:merchant_settlement',
    'transport': 'institution:agentpay:mobility_settlement',
    'healthcare': 'institution:glcb:health_billing',
    'insurance': 'institution:insurance:claims_reserve',
    'communications': 'institution:merchant:merchant_settlement',
    'discretionary': 'institution:merchant:merchant_settlement',
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


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def tail_jsonl(path: Path, n: int = 40) -> list[dict[str, Any]]:
    if not path.exists(): return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines()[-n:]:
        try:
            row = json.loads(line)
            if isinstance(row, dict): out.append(row)
        except Exception:
            pass
    return out


def stable_rng(*parts: Any) -> random.Random:
    seed = int(hashlib.sha256('|'.join(str(x) for x in parts).encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def hash_id(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:n]


def current_year_week() -> tuple[int, int]:
    cp = read_json(WORLD / 'checkpoint.json', {})
    for obj in (cp, cp.get('time', {}) if isinstance(cp, dict) else {}):
        if isinstance(obj, dict):
            try:
                y = int(obj.get('year', obj.get('current_year', 2045)))
                w = int(obj.get('week', obj.get('current_week', 1)))
                return y, w
            except Exception:
                pass
    return 2045, 1


def world_key(year: int, week: int) -> str:
    return f'Y{year}-W{week:02d}'


def policy() -> dict[str, Any]:
    raw = read_json(POLICY_PATH, {})
    if not isinstance(raw, dict) or not raw.get('taxes'):
        raw = DEFAULT_POLICY
        write_json(POLICY_PATH, raw)
    return raw


def persona_names() -> list[str]:
    root = WORLD / 'persona'
    return sorted([p.name for p in root.iterdir() if p.is_dir()]) if root.exists() else []


def career_state() -> dict[str, Any]:
    raw = read_json(WORLD / 'career' / 'state.json', {})
    return raw if isinstance(raw, dict) else {}


def finance_accounts() -> dict[str, dict[str, Any]]:
    raw = read_json(WORLD / 'finance' / 'accounts.json', {})
    src = raw.get('accounts', raw) if isinstance(raw, dict) else {}
    return {str(k): dict(v) for k, v in src.items() if isinstance(v, dict)} if isinstance(src, dict) else {}


def balances_by_name() -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in finance_accounts().values():
        if rec.get('owner_type') == 'citizen' and rec.get('owner'):
            out[str(rec['owner'])] = int(rec.get('balance', 0))
    return out


def humanity_index() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    people = read_json(WORLD / 'humanity' / 'people.json', {})
    by_name: dict[str, dict[str, Any]] = {}
    by_household: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if isinstance(people, dict):
        for p in people.values():
            if not isinstance(p, dict) or not p.get('alive', True): continue
            name = str(p.get('name') or '')
            if name: by_name[name] = p
            hid = str(p.get('household_id') or '')
            if hid and hid != 'unassigned': by_household[hid].append(p)
    return by_name, by_household


def build_household_blueprint() -> dict[str, dict[str, Any]]:
    """Use lifecycle household identity as the canonical household graph.

    Human Economy still tracks which members have full Agentopia persona/finance
    state, but household size, stages and family co-residence come from the full
    living lifecycle population so children/seniors/background residents are not
    silently omitted from household costs.
    """
    persona_set = set(persona_names())
    by_name, human_households = humanity_index()
    result: dict[str, dict[str, Any]] = {}

    # Canonical lifecycle households first.
    for hid, humans in sorted(human_households.items()):
        living = [p for p in humans if isinstance(p, dict) and p.get('alive', True)]
        names = sorted(str(p.get('name') or '') for p in living if p.get('name'))
        persona_members = sorted(n for n in names if n in persona_set)
        stages = [str(p.get('life_stage') or 'adult') for p in living]
        result[hid] = {
            'household_id': hid,
            'members': persona_members,
            'all_members': names,
            'household_size': max(len(living), 1),
            'life_stages': stages or ['adult'],
            'source': 'humanity.people.household_id',
        }

    # Safety compatibility for any persona absent from lifecycle state.
    covered = {name for rec in result.values() for name in rec.get('all_members', [])}
    for name in sorted(persona_set - covered):
        hid = f'HH-{hash_id(name, 12)}'
        age = int(by_name.get(name, {}).get('age', 35) or 35)
        stage = 'teen' if age < 18 else ('senior' if age >= 65 else 'adult')
        result[hid] = {
            'household_id': hid,
            'members': [name],
            'all_members': [name],
            'household_size': 1,
            'life_stages': [stage],
            'source': 'economy_compat_singleton',
        }
    return result


def housing_stock() -> dict[str, Any]:
    raw = read_json(HOUSING_PATH, {})
    if isinstance(raw, dict) and isinstance(raw.get('units'), dict) and raw['units']:
        return raw
    units: dict[str, dict[str, Any]] = {}
    rng = stable_rng('agentopia-detroit-housing-v170')
    for i in range(220):
        neighborhood, nidx = NEIGHBORHOODS[i % len(NEIGHBORHOODS)]
        kind, bedrooms, base_rent = UNIT_TYPES[(i * 7 + i // 11) % len(UNIT_TYPES)]
        jitter = rng.uniform(0.90, 1.12)
        rent = max(58, int(round(base_rent * nidx * jitter)))
        value = int(round(rent * 52 * rng.uniform(13.0, 17.5) / 1000.0) * 1000)
        condition = max(45, min(98, int(rng.gauss(78, 11))))
        pid = f'DET-HOME-{i+1:04d}'
        units[pid] = {
            'property_id': pid, 'neighborhood': neighborhood, 'neighborhood_index': nidx,
            'type': kind, 'bedrooms': bedrooms, 'weekly_rent_base': rent,
            'market_value_base': value, 'condition': condition,
            'occupied_by': None, 'created_version': VERSION,
        }
    raw = {'version': VERSION, 'updated_at': utc_now(), 'units': units}
    write_json(HOUSING_PATH, raw)
    return raw


def ensure_housing_capacity(housing: dict[str, Any], needed: int) -> None:
    units = housing.setdefault('units', {})
    if len(units) >= needed + 35: return
    start = len(units)
    rng = stable_rng('housing-expansion', start)
    for i in range(start, needed + 70):
        neighborhood, nidx = NEIGHBORHOODS[i % len(NEIGHBORHOODS)]
        kind, bedrooms, base_rent = UNIT_TYPES[(i * 5 + 3) % len(UNIT_TYPES)]
        rent = max(58, int(round(base_rent * nidx * rng.uniform(0.90, 1.12))))
        value = int(round(rent * 52 * rng.uniform(13.0, 17.5) / 1000.0) * 1000)
        pid = f'DET-HOME-{i+1:04d}'
        units[pid] = {'property_id':pid,'neighborhood':neighborhood,'neighborhood_index':nidx,'type':kind,'bedrooms':bedrooms,'weekly_rent_base':rent,'market_value_base':value,'condition':max(45,min(98,int(rng.gauss(78,11)))),'occupied_by':None,'created_version':VERSION}
    housing['updated_at'] = utc_now()


def _household_income(members: list[str], careers: dict[str, Any]) -> int:
    people = careers.get('citizens', {}) if isinstance(careers, dict) else {}
    total = 0
    for name in members:
        rec = people.get(name, {}) if isinstance(people, dict) else {}
        total += max(0, int(rec.get('weekly_income', 0) or 0))
    return total


def choose_unit(hid: str, hh: dict[str, Any], housing: dict[str, Any], income: int, cash: int) -> tuple[str, str]:
    units = housing['units']
    target = max(70, int(max(income, 260) * 0.28))
    needed_bed = max(0, min(4, int(math.ceil(max(1, int(hh.get('household_size', 1))) / 2))))
    candidates = [u for u in units.values() if not u.get('occupied_by')]
    if not candidates:
        ensure_housing_capacity(housing, len(units) + 50)
        candidates = [u for u in housing['units'].values() if not u.get('occupied_by')]
    rng = stable_rng(hid, 'housing-choice')
    def score(u: dict[str, Any]) -> float:
        rent = int(u.get('weekly_rent_base', 100))
        bedroom_penalty = max(0, needed_bed - int(u.get('bedrooms', 0))) * 95
        over_penalty = max(0, rent - target) * 1.6
        return abs(rent - target) + bedroom_penalty + over_penalty + rng.random() * 3
    unit = min(candidates, key=score)
    if cash >= 35000 and income >= 900:
        tenure = 'owned'
    elif cash >= 8000 and income >= 600 and stable_rng(hid, 'tenure').random() < 0.45:
        tenure = 'mortgage'
    else:
        tenure = 'rent'
    unit['occupied_by'] = hid
    return str(unit['property_id']), tenure


def housing_weekly_cost(unit: dict[str, Any], tenure: str, price_indices: dict[str, float]) -> int:
    hi = float(price_indices.get('housing', 1.0))
    rent = int(round(int(unit.get('weekly_rent_base', 90)) * hi))
    value = int(round(int(unit.get('market_value_base', 90000)) * hi))
    if tenure == 'owned':
        return max(28, int(value * 0.00058))
    if tenure == 'mortgage':
        return max(55, int(value * 0.00145))
    return rent


def initialize_households() -> tuple[dict[str, Any], dict[str, Any]]:
    blueprint = build_household_blueprint()
    careers = career_state()
    balances = balances_by_name()
    housing = housing_stock()
    ensure_housing_capacity(housing, len(blueprint))
    current = read_json(HOUSEHOLDS_PATH, {})
    households = current.get('households', {}) if isinstance(current, dict) else {}
    if not isinstance(households, dict): households = {}
    for hid, hh in blueprint.items():
        rec = households.get(hid, {}) if isinstance(households.get(hid), dict) else {}
        rec.update({k:v for k,v in hh.items() if k in {'household_id','members','all_members','household_size','life_stages','source'}})
        rec.setdefault('created_at', utc_now())
        rec.setdefault('arrears', {})
        rec.setdefault('hardship_weeks', 0)
        rec.setdefault('status', 'stable')
        if not rec.get('property_id') or rec.get('property_id') not in housing['units']:
            income = _household_income(hh['members'], careers)
            cash = sum(int(balances.get(n, 0)) for n in hh['members'])
            pid, tenure = choose_unit(hid, hh, housing, income, cash)
            rec['property_id'] = pid; rec['tenure'] = tenure; rec['moved_at'] = utc_now()
        else:
            housing['units'][rec['property_id']]['occupied_by'] = hid
        households[hid] = rec
    out = {'version': VERSION, 'updated_at': utc_now(), 'households': households}
    write_json(HOUSEHOLDS_PATH, out); write_json(HOUSING_PATH, housing)
    return out, housing


def market() -> dict[str, Any]:
    raw = read_json(MARKET_PATH, {})
    if isinstance(raw, dict) and raw.get('price_indices'): return raw
    y, w = current_year_week()
    raw = {'version': VERSION, 'updated_at': utc_now(), 'last_week': world_key(y,w), 'cpi':100.0, 'weekly_inflation_pct':0.0, 'annualized_inflation_pct':0.0, 'price_indices':{k:1.0 for k in PRICE_CATEGORIES}}
    write_json(MARKET_PATH, raw); return raw


def evolve_market(year: int, week: int, raw: dict[str, Any]) -> dict[str, Any]:
    key = world_key(year, week)
    if raw.get('last_week') == key: return raw
    rng = stable_rng('prices', year, week)
    drift = {'housing':0.0008,'groceries':0.0006,'utilities':0.0005,'transport':0.0004,'healthcare':0.0007,'insurance':0.0006,'communications':0.0002,'discretionary':0.0004}
    before = float(raw.get('cpi',100.0))
    idx = raw.setdefault('price_indices', {})
    for cat in PRICE_CATEGORIES:
        shock = rng.uniform(-0.0007, 0.0013)
        idx[cat] = round(max(0.75, float(idx.get(cat,1.0)) * (1 + drift[cat] + shock)), 5)
    weights = {'housing':0.30,'groceries':0.18,'utilities':0.10,'transport':0.12,'healthcare':0.10,'insurance':0.06,'communications':0.05,'discretionary':0.09}
    cpi = 100 * sum(float(idx[k]) * weights[k] for k in weights)
    weekly = ((cpi / before) - 1) * 100 if before else 0
    annual = ((1 + weekly/100) ** 52 - 1) * 100 if weekly > -100 else 0
    raw.update({'updated_at':utc_now(),'last_week':key,'cpi':round(cpi,2),'weekly_inflation_pct':round(weekly,3),'annualized_inflation_pct':round(annual,2)})
    write_json(MARKET_PATH, raw); return raw


def federal_rate(income: int, pol: dict[str, Any]) -> float:
    for ceiling, rate in pol['taxes']['federal_effective_brackets']:
        if income <= int(ceiling): return float(rate)
    return 0.20


def tax_due(income: int, pol: dict[str, Any]) -> int:
    if income <= 0: return 0
    t = pol['taxes']
    rate = float(t['city_income_rate']) + float(t['state_income_rate']) + float(t['payroll_rate']) + federal_rate(income, pol)
    return max(0, int(round(income * rate)))


def food_cost(stages: list[str], pol: dict[str, Any], idx: float) -> int:
    c = pol['weekly_cost_baseline']; total = 0
    for s in stages:
        s = str(s)
        if s == 'baby': base = c['food_baby']
        elif s in {'child','toddler'}: base = c['food_child']
        elif s == 'teen': base = c['food_teen']
        elif s in {'senior','elder'}: base = c['food_senior']
        else: base = c['food_adult']
        total += int(base)
    return int(round(total * idx))


def adult_child_counts(stages: list[str]) -> tuple[int,int]:
    adults = sum(1 for s in stages if s not in {'baby','toddler','child','teen'})
    children = len(stages) - adults
    return max(adults,1), children


def spending_propensity(name: str, year: int, week: int) -> float:
    rng = stable_rng(name, year, week, 'spending')
    return rng.uniform(0.035, 0.10)


def _gini(values: list[float]) -> float:
    xs = sorted(max(0.0, float(x)) for x in values)
    n = len(xs); total = sum(xs)
    if n == 0 or total <= 0: return 0.0
    weighted = sum((i+1)*x for i,x in enumerate(xs))
    return round((2*weighted)/(n*total) - (n+1)/n, 3)


def _economic_class(income: int, size: int, hardship: int, net_worth: int) -> str:
    per = income / max(1,size)
    if hardship >= 60 or per < 210: return 'hardship'
    if per < 340: return 'working'
    if per < 600: return 'middle'
    if per < 900: return 'upper_middle'
    if per < 1400 and net_worth < 120000: return 'affluent'
    return 'wealthy'


def finance_runtime(world: Any):
    try:
        import detroit_financial_system as fin
        accounts = fin._accounts(); state = fin._state(); fin._ensure_base_accounts(accounts)
        return fin, accounts, state
    except Exception:
        return None, {}, {}


def debit(fin_ctx: tuple[Any,dict[str,Any],dict[str,Any]], agent: Any, name: str, amount: int, category: str, key: str, time_text: str, description: str) -> tuple[int,int]:
    amount = max(0, int(amount))
    if amount <= 0: return 0, 0
    try: before = max(0, int(agent.dm.get_deposit()))
    except Exception: return 0, amount
    actual = min(before, amount)
    if actual > 0:
        try: agent.dm.update_deposit(before - actual)
        except Exception: return 0, amount
    fin, accounts, fstate = fin_ctx
    if fin is not None and actual > 0:
        try:
            aid = fin._ensure_citizen_account(accounts, name, before)
            if int(accounts[aid].get('balance',0)) != before: accounts[aid]['balance'] = before
            fin._transfer(accounts, fstate, aid, DESTINATION[category], actual, key, time_text, f'human_{category}', description, {'citizen':name,'human_economy_version':VERSION})
        except Exception:
            pass
    append_jsonl(LEDGER_PATH, {'time':utc_now(),'world_week':key,'citizen':name,'category':category,'due':amount,'paid':actual,'shortfall':amount-actual,'description':description})
    return actual, amount-actual


def grant_aid(fin_ctx: tuple[Any,dict[str,Any],dict[str,Any]], agent: Any, name: str, amount: int, key: str, time_text: str) -> int:
    amount = max(0, int(amount)); fin, accounts, fstate = fin_ctx
    if amount <= 0: return 0
    posted = 0
    if fin is not None:
        try:
            before = max(0, int(agent.dm.get_deposit()))
            aid = fin._ensure_citizen_account(accounts, name, before)
            if int(accounts[aid].get('balance',0)) != before: accounts[aid]['balance'] = before
            posted = int(fin._transfer(accounts, fstate, 'institution:dcb:municipal_treasury', aid, amount, key, time_text, 'social_assistance', 'Human Economy household stabilization benefit', {'citizen':name,'human_economy_version':VERSION}))
            if posted > 0: agent.dm.update_deposit(before + posted)
        except Exception: posted = 0
    if posted:
        append_jsonl(LEDGER_PATH, {'time':utc_now(),'world_week':key,'citizen':name,'category':'assistance','due':0,'paid':posted,'shortfall':0,'description':'City household stabilization benefit'})
    return posted


def save_finance(fin_ctx: tuple[Any,dict[str,Any],dict[str,Any]], world: Any) -> None:
    fin, accounts, fstate = fin_ctx
    if fin is None: return
    try:
        fstate['updated_at'] = utc_now(); fin._save_accounts(accounts); fin._write_json(fin.STATE_PATH, fstate); fin._build_summary(world)
    except Exception:
        pass


def household_shared_costs(hh: dict[str,Any], unit: dict[str,Any], tenure: str, pol: dict[str,Any], mkt: dict[str,Any]) -> dict[str,int]:
    idx = mkt.get('price_indices', {})
    stages = list(hh.get('life_stages') or ['adult'])
    adults, children = adult_child_counts(stages)
    size = max(1, int(hh.get('household_size',len(stages) or 1)))
    c = pol['weekly_cost_baseline']
    return {
        'housing': housing_weekly_cost(unit, tenure, idx),
        'utilities': int(round((int(c['utilities_base']) + int(c['utilities_per_person'])*size) * float(idx.get('utilities',1.0)))),
        'food': food_cost(stages, pol, float(idx.get('groceries',1.0))),
        'transport': int(round(int(c['transport_per_adult']) * adults * float(idx.get('transport',1.0)))),
        'healthcare': int(round((int(c['health_per_adult'])*adults + int(c['health_per_child'])*children) * float(idx.get('healthcare',1.0)))),
        'insurance': int(round((10 + (6 if tenure in {'owned','mortgage'} else 2) + 3*adults) * float(idx.get('insurance',1.0)))),
        'communications': int(round((int(c['communications_base']) + int(c['communications_per_person'])*size) * float(idx.get('communications',1.0)))),
    }


def household_net_worth(hh: dict[str,Any], unit: dict[str,Any], balances: dict[str,int], mkt: dict[str,Any]) -> int:
    cash = sum(int(balances.get(n,0)) for n in hh.get('members',[]))
    tenure = str(hh.get('tenure') or 'rent')
    if tenure == 'rent': return cash
    value = int(int(unit.get('market_value_base',0)) * float(mkt.get('price_indices',{}).get('housing',1.0)))
    equity = value if tenure == 'owned' else int(value * 0.28)
    return cash + equity


def maybe_move_for_hardship(hid: str, rec: dict[str,Any], housing: dict[str,Any], mkt: dict[str,Any], year: int, week: int) -> None:
    pol = policy(); threshold = int(pol['housing']['hardship_move_after_weeks'])
    if int(rec.get('housing_shortfall_weeks',0)) < threshold: return
    old_id = str(rec.get('property_id') or ''); old = housing.get('units',{}).get(old_id)
    if not old: return
    old_cost = housing_weekly_cost(old, str(rec.get('tenure') or 'rent'), mkt.get('price_indices',{}))
    options = [u for u in housing.get('units',{}).values() if not u.get('occupied_by') and int(u.get('weekly_rent_base',9999)) < old_cost * 0.78]
    if not options:
        rec['status'] = 'housing_insecure'; return
    rng = stable_rng(hid,year,week,'move')
    options.sort(key=lambda u:(int(u.get('weekly_rent_base',9999)),rng.random()))
    new = options[0]
    old['occupied_by'] = None; new['occupied_by'] = hid
    rec['property_id'] = new['property_id']; rec['tenure'] = 'rent'; rec['moved_at'] = f'Y{year}-W{week:02d}'
    rec['housing_shortfall_weeks'] = 0; rec['status'] = 'downsized_after_hardship'
    append_jsonl(EVENTS_PATH, {'time':utc_now(),'world_week':world_key(year,week),'event':'housing_move_for_affordability','household_id':hid,'from_neighborhood':old.get('neighborhood'),'to_neighborhood':new.get('neighborhood'),'new_weekly_rent':new.get('weekly_rent_base')})


def process_week(world: Any) -> None:
    y = int(getattr(world.clock.get_time(),'year',2045)); w = int(getattr(world.clock.get_time(),'week',1)); key = world_key(y,w); time_text = str(world.clock.get_time())
    state = read_json(STATE_PATH, {'version':VERSION,'last_processed_week':None,'citizens':{},'cumulative':{}})
    if state.get('last_processed_week') == key:
        build_summary(state); return
    households_doc, housing = initialize_households(); households = households_doc['households']
    mkt = evolve_market(y,w,market()); pol = policy(); careers = career_state(); cpeople = careers.get('citizens',{}) if isinstance(careers,dict) else {}
    agents = {str(a.name):a for a in getattr(world,'agents',[])}
    fin_ctx = finance_runtime(world)
    spending = Counter(); tax_total = 0; aid_total = 0; shortfall_total = 0
    citizen_state = state.setdefault('citizens',{})
    for hid, hh in households.items():
        active = [n for n in hh.get('members',[]) if n in agents]
        if not active: continue
        unit = housing['units'].get(hh.get('property_id'), {})
        if not unit: continue
        incomes = {n:max(0,int((cpeople.get(n,{}) if isinstance(cpeople,dict) else {}).get('weekly_income',0))) for n in active}
        # Fallback to the live DataManager if a career record is missing.
        for n in active:
            if incomes[n] <= 0:
                try: incomes[n] = max(0,int(agents[n].dm.get_weekly_income()))
                except Exception: pass
        gross = sum(incomes.values()); costs = household_shared_costs(hh,unit,str(hh.get('tenure') or 'rent'),pol,mkt)
        shares = {n:(incomes[n]/gross if gross>0 else 1/len(active)) for n in active}
        hh_paid = Counter(); hh_short = Counter(); member_budgets: dict[str,Any] = {}
        # Withholding-style taxes first.
        for n in active:
            due = tax_due(incomes[n], pol); paid, short = debit(fin_ctx,agents[n],n,due,'taxes',key,time_text,'Detroit/MI/federal modeled withholding')
            tax_total += paid; spending['taxes'] += paid; hh_paid['taxes'] += paid; hh_short['taxes'] += short
            member_budgets[n] = {'gross_income':incomes[n],'tax_due':due,'tax_paid':paid,'shared_costs_paid':0,'discretionary_paid':0}
        # Essential household obligations.
        for cat in ['housing','utilities','food','transport','healthcare','insurance','communications']:
            remaining = int(costs[cat])
            for i,n in enumerate(active):
                due = remaining if i == len(active)-1 else int(round(costs[cat]*shares[n]))
                remaining -= due
                paid, short = debit(fin_ctx,agents[n],n,due,cat,key,time_text,f'{cat.title()} household obligation for {hid}')
                spending[cat] += paid; hh_paid[cat] += paid; hh_short[cat] += short; member_budgets[n]['shared_costs_paid'] += paid
        # Discretionary spending is bounded by what remains after essentials.
        for n in active:
            try: bal = max(0,int(agents[n].dm.get_deposit()))
            except Exception: bal = 0
            discretionary_due = min(int(incomes[n]*spending_propensity(n,y,w)*float(mkt.get('price_indices',{}).get('discretionary',1.0))), max(0,bal-40))
            paid, short = debit(fin_ctx,agents[n],n,discretionary_due,'discretionary',key,time_text,'Personal dining, entertainment, clothing and discretionary purchases')
            spending['discretionary'] += paid; hh_paid['discretionary'] += paid; hh_short['discretionary'] += short; member_budgets[n]['discretionary_paid'] = paid
        essential_shortfall = sum(int(v) for k,v in hh_short.items() if k != 'discretionary')
        shortfall_total += essential_shortfall
        arrears = hh.setdefault('arrears',{})
        for cat,amt in hh_short.items():
            if amt > 0 and cat != 'discretionary': arrears[cat] = int(arrears.get(cat,0)) + int(amt)
        if int(hh_short.get('housing',0)) > 0: hh['housing_shortfall_weeks'] = int(hh.get('housing_shortfall_weeks',0)) + 1
        else: hh['housing_shortfall_weeks'] = 0
        end_bal = 0
        for n in active:
            try:
                b = max(0,int(agents[n].dm.get_deposit())); end_bal += b; member_budgets[n]['ending_balance'] = b
            except Exception: member_budgets[n]['ending_balance'] = 0
        if essential_shortfall > 0: hh['hardship_weeks'] = int(hh.get('hardship_weeks',0)) + 1
        else: hh['hardship_weeks'] = max(0,int(hh.get('hardship_weeks',0))-1)
        hardship = min(100, int(hh.get('hardship_weeks',0))*12 + min(55,int(sum(int(v) for v in arrears.values())/max(1,gross)*18)))
        # Safety net only when cash is genuinely low and household earnings are modest.
        if pol['safety_net']['enabled'] and end_bal < int(pol['safety_net']['cash_floor']) and gross < 650 and active:
            need = min(int(pol['safety_net']['max_weekly_household_aid']), max(0,int(pol['safety_net']['cash_floor'])-end_bal)+35)
            target = min(active, key=lambda n:int(member_budgets[n].get('ending_balance',0)))
            aid = grant_aid(fin_ctx,agents[target],target,need,key,time_text)
            aid_total += aid; spending['assistance'] += aid; end_bal += aid; member_budgets[target]['ending_balance'] += aid
            if aid: append_jsonl(EVENTS_PATH, {'time':utc_now(),'world_week':key,'event':'household_assistance','household_id':hid,'citizen':target,'amount':aid})
        hh['last_budget'] = {'world_week':key,'gross_income':gross,'paid':dict(hh_paid),'shortfall':dict(hh_short),'ending_cash':end_bal,'essential_shortfall':essential_shortfall,'member_budgets':member_budgets}
        hh['hardship_score'] = hardship
        balances = {n:int(member_budgets.get(n,{}).get('ending_balance',0)) for n in hh.get('members',[])}
        net = household_net_worth(hh,unit,balances,mkt); hh['net_worth_estimate'] = net; hh['economic_class'] = _economic_class(gross,int(hh.get('household_size',1)),hardship,net)
        hh['updated_at'] = utc_now()
        for n in active:
            citizen_state[n] = {'household_id':hid,'world_week':key,'gross_income':incomes[n],**member_budgets[n],'economic_class':hh['economic_class'],'hardship_score':hardship,'neighborhood':unit.get('neighborhood'),'tenure':hh.get('tenure'),'property_id':hh.get('property_id')}
        maybe_move_for_hardship(hid,hh,housing,mkt,y,w)
    state['version'] = VERSION; state['last_processed_week'] = key; state['updated_at'] = utc_now()
    cum = state.setdefault('cumulative',{})
    cum['tax_revenue'] = int(cum.get('tax_revenue',0)) + tax_total; cum['consumer_spending'] = int(cum.get('consumer_spending',0)) + sum(v for k,v in spending.items() if k not in {'taxes','assistance'}); cum['assistance'] = int(cum.get('assistance',0)) + aid_total
    state['last_week'] = {'world_week':key,'tax_revenue':tax_total,'consumer_spending':sum(v for k,v in spending.items() if k not in {'taxes','assistance'}),'assistance':aid_total,'essential_shortfall':shortfall_total,'spending_categories':dict(spending)}
    write_json(STATE_PATH,state); write_json(HOUSEHOLDS_PATH,households_doc); write_json(HOUSING_PATH,housing); save_finance(fin_ctx,world); build_summary(state)
    append_jsonl(EVENTS_PATH, {'time':utc_now(),'world_week':key,'event':'human_economy_week_settled','households_processed':sum(1 for h in households.values() if any(n in agents for n in h.get('members',[]))),'tax_revenue':tax_total,'consumer_spending':state['last_week']['consumer_spending'],'assistance':aid_total,'essential_shortfall':shortfall_total})
    try: world.logger.info('[ECON170] Human Economy settled %s: taxes=$%d spending=$%d aid=$%d shortfall=$%d',key,tax_total,state['last_week']['consumer_spending'],aid_total,shortfall_total)
    except Exception: pass


def municipal_balance() -> int:
    a = finance_accounts(); return int(a.get('institution:dcb:municipal_treasury',{}).get('balance',0))


def build_summary(state: dict[str,Any] | None = None) -> dict[str,Any]:
    state = state or read_json(STATE_PATH,{})
    hhdoc = read_json(HOUSEHOLDS_PATH,{'households':{}}); households = hhdoc.get('households',{}) if isinstance(hhdoc,dict) else {}
    housing = housing_stock(); units = housing.get('units',{})
    mkt = market(); all_hh = [h for h in households.values() if isinstance(h,dict)]; active_hh = [h for h in all_hh if h.get('last_budget')]
    careers = career_state(); cash_balances = balances_by_name()
    incomes: list[int] = []; housing_costs = []
    classes = Counter(); tenures = Counter(); hardship = 0; arrears_total = 0
    neighborhood: dict[str,dict[str,Any]] = defaultdict(lambda:{'households':0,'renters':0,'owners':0,'weekly_housing_costs':[],'income':[]})
    for h in all_hh:
        unit = units.get(h.get('property_id'),{})
        cost = housing_weekly_cost(unit,str(h.get('tenure') or 'rent'),mkt.get('price_indices',{})); housing_costs.append(cost)
        income = int(h.get('last_budget',{}).get('gross_income',0)) if h.get('last_budget') else _household_income(list(h.get('members',[])),careers)
        incomes.append(income)
        net = int(h.get('net_worth_estimate', household_net_worth(h,unit,cash_balances,mkt)))
        cls = str(h.get('economic_class') or _economic_class(income,int(h.get('household_size',1)),int(h.get('hardship_score',0)),net))
        classes[cls] += 1; tenures[str(h.get('tenure') or 'rent')] += 1
        if int(h.get('hardship_score',0)) >= 50: hardship += 1
        arrears_total += sum(int(x) for x in (h.get('arrears') or {}).values())
        n = str(unit.get('neighborhood') or 'Unknown'); neighborhood[n]['households'] += 1; neighborhood[n]['weekly_housing_costs'].append(cost); neighborhood[n]['income'].append(income)
        if h.get('tenure') == 'rent': neighborhood[n]['renters'] += 1
        else: neighborhood[n]['owners'] += 1
    nh = []
    for name, rec in sorted(neighborhood.items()):
        nh.append({'neighborhood':name,'households':rec['households'],'renters':rec['renters'],'owners':rec['owners'],'median_weekly_housing_cost':int(median(rec['weekly_housing_costs'])) if rec['weekly_housing_costs'] else 0,'median_weekly_household_income':int(median(rec['income'])) if rec['income'] else 0})
    last = state.get('last_week',{}) if isinstance(state,dict) else {}
    total_occupied = sum(1 for u in units.values() if u.get('occupied_by'))
    out = {
        'version':VERSION,'updated_at':utc_now(),'world_week':state.get('last_processed_week'),'households':len(all_hh),'settled_households':len(active_hh),'housing_units':len(units),'occupied_units':total_occupied,'vacant_units':max(0,len(units)-total_occupied),
        'household_truth':'humanity.people.household_id',
        'homeownership_rate':round(100*sum(v for k,v in tenures.items() if k in {'owned','mortgage'})/max(1,sum(tenures.values())),1),
        'median_weekly_household_income':int(median(incomes)) if incomes else 0,'median_weekly_housing_cost':int(median(housing_costs)) if housing_costs else 0,
        'hardship_households':hardship,'hardship_rate':round(100*hardship/max(1,len(all_hh)),1),'arrears_total':arrears_total,'economic_classes':dict(classes),'tenure':dict(tenures),
        'cpi':mkt.get('cpi',100.0),'weekly_inflation_pct':mkt.get('weekly_inflation_pct',0.0),'annualized_inflation_pct':mkt.get('annualized_inflation_pct',0.0),'price_indices':mkt.get('price_indices',{}),
        'tax_revenue_week':int(last.get('tax_revenue',0)),'consumer_spending_week':int(last.get('consumer_spending',0)),'assistance_week':int(last.get('assistance',0)),'essential_shortfall_week':int(last.get('essential_shortfall',0)),'spending_categories':last.get('spending_categories',{}),
        'cumulative':state.get('cumulative',{}),'municipal_treasury':municipal_balance(),'income_gini':_gini(incomes),'neighborhoods':nh,
        'hardship_households_detail':sorted([{'household_id':h.get('household_id'),'members':h.get('members',[]),'economic_class':h.get('economic_class'),'hardship_score':int(h.get('hardship_score',0)),'arrears':sum(int(x) for x in (h.get('arrears') or {}).values()),'ending_cash':int(h.get('last_budget',{}).get('ending_cash',0))} for h in active_hh],key=lambda x:(x['hardship_score'],x['arrears']),reverse=True)[:20],
        'recent_events':tail_jsonl(EVENTS_PATH,40),'recent_transactions':tail_jsonl(LEDGER_PATH,60),
        'principles':{'existing_balances_preserved_on_install':True,'no_current_week_retroactive_debit':True,'costs_post_against_financial_network':True,'housing_is_persistent':True,'policy_is_fictional_2045_simulation':True,'protected_traits_not_used_for_economic_eligibility':True},
    }
    write_json(SUMMARY_PATH,out); return out

def initialize() -> dict[str,Any]:
    ECON.mkdir(parents=True,exist_ok=True); policy(); initialize_households(); market()
    state = read_json(STATE_PATH,{})
    if not isinstance(state,dict): state = {}
    y,w = current_year_week(); state.setdefault('version',VERSION); state['version']=VERSION; state.setdefault('citizens',{}); state.setdefault('cumulative',{})
    # Critical install behavior: mark the current world week as already processed.
    # v1.7.0 begins charging costs at the NEXT natural week boundary.
    if not state.get('last_processed_week'): state['last_processed_week'] = world_key(y,w)
    state['updated_at'] = utc_now(); write_json(STATE_PATH,state)
    return build_summary(state)


def economy_context(name: str) -> str:
    state = read_json(STATE_PATH,{}); crec = (state.get('citizens') or {}).get(name,{}) if isinstance(state,dict) else {}
    if not crec: return ''
    hhdoc = read_json(HOUSEHOLDS_PATH,{'households':{}}); hh = (hhdoc.get('households') or {}).get(crec.get('household_id'),{}) if isinstance(hhdoc,dict) else {}
    housing = read_json(HOUSING_PATH,{'units':{}}); unit = (housing.get('units') or {}).get(hh.get('property_id'),{}) if isinstance(housing,dict) else {}
    b = hh.get('last_budget',{}) if isinstance(hh,dict) else {}; arrears = sum(int(x) for x in (hh.get('arrears') or {}).values()) if isinstance(hh,dict) else 0
    lines = [
        f'## Agentopia Human Economy v{VERSION}',
        f"- Household: {int(hh.get('household_size',1) or 1)} people; economic class: {hh.get('economic_class','unknown')}; hardship score {int(hh.get('hardship_score',0))}/100.",
        f"- Home: {unit.get('type','housing')} in {unit.get('neighborhood','Detroit')} ({hh.get('tenure','rent')}); household housing cost about ${housing_weekly_cost(unit,str(hh.get('tenure') or 'rent'),market().get('price_indices',{})):,}/week.",
        f"- Your most recent weekly budget: gross ${int(crec.get('gross_income',0)):,}; taxes paid ${int(crec.get('tax_paid',0)):,}; shared essentials paid ${int(crec.get('shared_costs_paid',0)):,}; discretionary spending ${int(crec.get('discretionary_paid',0)):,}; ending cash ${int(crec.get('ending_balance',0)):,}.",
    ]
    if arrears: lines.append(f'- Household arrears: ${arrears:,}. Financial pressure should influence choices, but you may seek work, cut spending, move, ask for help, retrain, or take other lawful actions.')
    else: lines.append('- You have no recorded household arrears this week.')
    lines.append('- You are not a perfect economic optimizer. Family, relationships, pride, habit, stress, values and imperfect judgment can affect what you choose to do.')
    return '\n'.join(lines)


def apply_runtime_patches() -> None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.world.world import World
    if not getattr(DataManager.character_prompt,'_agentopia_human_economy_v170',False):
        original = DataManager.character_prompt
        def economy_prompt(self):
            base = original(self)
            try:
                ctx = economy_context(self.char)
                return str(base) + ('\n\n'+ctx if ctx else '')
            except Exception: return base
        economy_prompt._agentopia_human_economy_v170 = True; DataManager.character_prompt = economy_prompt
    # Run AFTER the complete existing week-start chain so Career selects current pay,
    # Agentopia pays wages, Mission/Finance synchronize, and only then do households spend.
    if not getattr(World._before_week_start,'_agentopia_human_economy_v170',False):
        original_before = World._before_week_start
        def economy_before(self):
            result = original_before(self)
            try: process_week(self)
            except Exception as e:
                try: self.logger.warning('[ECON170] week settlement failed: %s', e)
                except Exception: pass
            return result
        economy_before._agentopia_human_economy_v170 = True; World._before_week_start = economy_before


def status() -> None:
    s = initialize()
    print(f'Agentopia Detroit Human Economy v{VERSION}')
    print('Households:',s.get('households'),'Housing units:',s.get('housing_units'),'Vacant:',s.get('vacant_units'))
    print('Homeownership:',str(s.get('homeownership_rate'))+'%','Median household income:',s.get('median_weekly_household_income'),'Median housing cost:',s.get('median_weekly_housing_cost'))
    print('Last week taxes:',s.get('tax_revenue_week'),'Consumer spending:',s.get('consumer_spending_week'),'Assistance:',s.get('assistance_week'))
    print('Hardship households:',s.get('hardship_households'),'Income Gini:',s.get('income_gini'),'CPI:',s.get('cpi'))
    print('State:',ECON)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('command',choices=['init','status'],nargs='?',default='status'); args = ap.parse_args()
    if args.command == 'init': initialize()
    status()
