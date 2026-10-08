#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
FIN = WORLD / "finance"
STATE_PATH = FIN / "state.json"
INSTITUTIONS_PATH = FIN / "institutions.json"
ACCOUNTS_PATH = FIN / "accounts.json"
ALERTS_PATH = FIN / "alerts.json"
MARKETS_PATH = FIN / "markets.json"
SUMMARY_PATH = FIN / "summary.json"
LEDGER_PATH = FIN / "ledger.ndjson"
VERSION = "1.6.1"
_LOCK = threading.Lock()

INSTITUTIONS = {
    "glcb": {"name": "Great Lakes Community Bank", "type": "commercial_bank", "risk": 22},
    "mccu": {"name": "Motor City Credit Union", "type": "credit_union", "risk": 18},
    "dcb": {"name": "Detroit Civic Bank", "type": "public_bank", "risk": 16},
    "agentpay": {"name": "AgentPay Settlement Rail", "type": "payment_network", "risk": 28},
    "clearing": {"name": "Detroit Clearing House", "type": "clearing_network", "risk": 20},
    "insurance": {"name": "Great Lakes Mutual Insurance", "type": "insurance", "risk": 24},
    "exchange": {"name": "Agentopia Exchange", "type": "securities_exchange", "risk": 26},
    "merchant": {"name": "Eastern Market Merchant Services", "type": "merchant_acquirer", "risk": 30},
}

TARGET_ACCOUNT_BY_CATEGORY = {
    "citizen_finance": "institution:glcb:customer_fraud_reserve",
    "municipal": "institution:dcb:municipal_treasury",
    "transit": "institution:dcb:transit_revenue",
    "small_business": "institution:merchant:merchant_settlement",
    "mobility": "institution:agentpay:mobility_settlement",
    "healthcare": "institution:glcb:health_billing",
    "utilities": "institution:dcb:utility_revenue",
    "banking": "institution:glcb:bank_operations",
    "payments": "institution:agentpay:settlement_reserve",
    "insurance": "institution:insurance:claims_reserve",
    "securities": "institution:exchange:clearing_reserve",
    "payroll": "institution:clearing:payroll_clearing",
    "credit": "institution:mccu:lending_reserve",
}

MISSION_TARGETS = [
    ("banking", "Great Lakes Community Bank Core Ledger"),
    ("payments", "AgentPay Settlement Rail"),
    ("insurance", "Great Lakes Mutual Claims Network"),
    ("securities", "Agentopia Exchange Clearing House"),
    ("payroll", "Detroit Civic Payroll Network"),
    ("credit", "Motor City Credit Union Lending Network"),
]

MISSION_METHODS = [
    "simulation-only bank-fraud operation",
    "abstract payment-diversion scenario",
    "synthetic claims-fraud operation",
    "simulation-only market-manipulation scenario",
    "abstract payroll-fraud operation",
    "synthetic lending-fraud operation",
]

MARKETS = {
    "DMI": {"name": "Detroit Mobility Index", "price": 100.0},
    "GLU": {"name": "Great Lakes Utilities", "price": 82.0},
    "AFI": {"name": "Agentopia Financial Index", "price": 120.0},
    "BFC": {"name": "Biofabrication Cooperative", "price": 74.0},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_ledger(row: dict[str, Any]) -> None:
    FIN.mkdir(parents=True, exist_ok=True)
    rec = dict(row)
    rec.setdefault("recorded_at", utc_now())
    rec.setdefault("engine", VERSION)
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _tail_ledger(n: int = 80) -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    try:
        lines = LEDGER_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []
    out = []
    for line in lines:
        try:
            x = json.loads(line)
            if isinstance(x, dict): out.append(x)
        except Exception:
            pass
    return out


def _stable_rng(*parts: Any) -> random.Random:
    seed = int(hashlib.sha256("|".join(str(x) for x in parts).encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def _state() -> dict[str, Any]:
    s = _read_json(STATE_PATH, {})
    if not isinstance(s, dict) or not s:
        s = {
            "version": VERSION,
            "initialized_at": utc_now(),
            "updated_at": utc_now(),
            "processed_operations": [],
            "transaction_seq": 0,
            "last_sync_week": "",
        }
        _write_json(STATE_PATH, s)
    return s


def _institutions() -> dict[str, Any]:
    raw = _read_json(INSTITUTIONS_PATH, {})
    if not isinstance(raw, dict) or not raw.get("institutions"):
        raw = {"version": VERSION, "updated_at": utc_now(), "institutions": INSTITUTIONS}
        _write_json(INSTITUTIONS_PATH, raw)
    return raw


def _accounts() -> dict[str, dict[str, Any]]:
    raw = _read_json(ACCOUNTS_PATH, {})
    src = raw.get("accounts", raw) if isinstance(raw, dict) else {}
    return {str(k): dict(v) for k, v in src.items() if isinstance(v, dict)}


def _save_accounts(accounts: dict[str, dict[str, Any]]) -> None:
    _write_json(ACCOUNTS_PATH, {"version": VERSION, "updated_at": utc_now(), "accounts": accounts})


def _alerts() -> list[dict[str, Any]]:
    raw = _read_json(ALERTS_PATH, {})
    src = raw.get("alerts", raw) if isinstance(raw, dict) else []
    return [dict(x) for x in src if isinstance(x, dict)] if isinstance(src, list) else []


def _save_alerts(alerts: list[dict[str, Any]]) -> None:
    _write_json(ALERTS_PATH, {"version": VERSION, "updated_at": utc_now(), "alerts": alerts[-300:]})


def _markets() -> dict[str, dict[str, Any]]:
    raw = _read_json(MARKETS_PATH, {})
    src = raw.get("markets", raw) if isinstance(raw, dict) else {}
    if not src:
        src = {k: dict(v, previous_price=v["price"], change_pct=0.0) for k, v in MARKETS.items()}
        _write_json(MARKETS_PATH, {"version": VERSION, "updated_at": utc_now(), "markets": src})
    return {str(k): dict(v) for k, v in src.items() if isinstance(v, dict)}


def _save_markets(markets: dict[str, dict[str, Any]]) -> None:
    _write_json(MARKETS_PATH, {"version": VERSION, "updated_at": utc_now(), "markets": markets})


def _world_key(world: Any) -> str:
    try:
        t = world.clock.get_time()
        return f"Y{int(t.year)}-W{int(t.week):02d}"
    except Exception:
        return "unknown"


def _world_time(world: Any) -> str:
    try: return str(world.clock.get_time())
    except Exception: return "unknown"


def _name_id(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def _ensure_base_accounts(accounts: dict[str, dict[str, Any]]) -> None:
    base = {
        "system:employer_payroll": ("System Payroll Clearing", "system", "clearing", 10**12),
        "system:consumption_sink": ("Household Consumption", "system", "clearing", 0),
        "system:crime_clearing": ("Compromised Funds Clearing", "system", "clearing", 0),
        "system:recovery_escrow": ("Guardian Recovery Escrow", "system", "dcb", 0),
        "faction:obsidian:treasury": ("Obsidian Network Treasury", "faction", "glcb", 50000),
        "faction:guardians:operating": ("ThAI Guardians Operating Fund", "faction", "dcb", 50000),
        "institution:glcb:customer_fraud_reserve": ("GLCB Customer Fraud Reserve", "institution", "glcb", 3000000),
        "institution:glcb:bank_operations": ("GLCB Bank Operations", "institution", "glcb", 12000000),
        "institution:glcb:health_billing": ("Community Health Billing", "institution", "glcb", 4500000),
        "institution:mccu:lending_reserve": ("MCCU Lending Reserve", "institution", "mccu", 6500000),
        "institution:dcb:municipal_treasury": ("Agentopia Municipal Treasury", "institution", "dcb", 18000000),
        "institution:dcb:transit_revenue": ("Autonomous Transit Revenue", "institution", "dcb", 3500000),
        "institution:dcb:utility_revenue": ("Civic Utility Revenue", "institution", "dcb", 5500000),
        "institution:agentpay:settlement_reserve": ("AgentPay Settlement Reserve", "institution", "agentpay", 9500000),
        "institution:agentpay:mobility_settlement": ("Mobility Settlement Pool", "institution", "agentpay", 4200000),
        "institution:clearing:payroll_clearing": ("Detroit Civic Payroll", "institution", "clearing", 7000000),
        "institution:insurance:claims_reserve": ("Great Lakes Mutual Claims Reserve", "institution", "insurance", 8500000),
        "institution:exchange:clearing_reserve": ("Agentopia Exchange Clearing Reserve", "institution", "exchange", 15000000),
        "institution:merchant:merchant_settlement": ("Eastern Market Merchant Settlement", "institution", "merchant", 3800000),
    }
    for aid, (name, owner_type, bank, balance) in base.items():
        accounts.setdefault(aid, {"account_id": aid, "name": name, "owner_type": owner_type, "bank_id": bank, "balance": int(balance), "frozen": 0, "status": "open"})


def _ensure_citizen_account(accounts: dict[str, dict[str, Any]], name: str, balance: int) -> str:
    aid = f"citizen:{_name_id(name)}:checking"
    accounts.setdefault(aid, {
        "account_id": aid,
        "name": f"{name} Checking",
        "owner": name,
        "owner_type": "citizen",
        "bank_id": "glcb" if int(_name_id(name)[0], 16) % 3 == 0 else ("mccu" if int(_name_id(name)[0], 16) % 3 == 1 else "dcb"),
        "balance": int(balance),
        "frozen": 0,
        "status": "open",
    })
    return aid


def _ensure_person_shadow(accounts: dict[str, dict[str, Any]], name: str, balance: int) -> str:
    return _ensure_citizen_account(accounts, name, balance)


def _display_account(accounts: dict[str, dict[str, Any]], aid: str | None) -> str:
    if not aid: return "External"
    return str(accounts.get(aid, {}).get("name", aid))


def _transfer(accounts: dict[str, dict[str, Any]], state: dict[str, Any], from_id: str, to_id: str, amount: int, world_week: str, world_time: str, tx_type: str, description: str, meta: dict[str, Any] | None = None, allow_overdraft: bool = False) -> int:
    amount = max(0, int(amount))
    if amount <= 0: return 0
    if from_id not in accounts or to_id not in accounts: return 0
    src, dst = accounts[from_id], accounts[to_id]
    available = max(0, int(src.get("balance", 0)) - int(src.get("frozen", 0)))
    actual = amount if allow_overdraft else min(amount, available)
    if actual <= 0: return 0
    src["balance"] = int(src.get("balance", 0)) - actual
    dst["balance"] = int(dst.get("balance", 0)) + actual
    state["transaction_seq"] = int(state.get("transaction_seq", 0)) + 1
    row = {
        "tx_id": f"TX-{state['transaction_seq']:09d}",
        "world_week": world_week,
        "world_time": world_time,
        "from_account": from_id,
        "from_name": _display_account(accounts, from_id),
        "to_account": to_id,
        "to_name": _display_account(accounts, to_id),
        "amount": actual,
        "type": tx_type,
        "description": description,
        "status": "posted",
    }
    if meta: row["metadata"] = meta
    _append_ledger(row)
    return actual


def _agent_map(world: Any) -> dict[str, Any]:
    return {a.name: a for a in getattr(world, "agents", [])}


def _sync_citizens(world: Any, accounts: dict[str, dict[str, Any]], state: dict[str, Any], reason: str) -> None:
    wk, wt = _world_key(world), _world_time(world)
    for ag in getattr(world, "agents", []):
        try: actual = int(ag.dm.get_deposit())
        except Exception: continue
        aid = _ensure_citizen_account(accounts, ag.name, actual)
        shadow = int(accounts[aid].get("balance", 0))
        delta = actual - shadow
        if delta > 0:
            _transfer(accounts, state, "system:employer_payroll", aid, delta, wk, wt, "income", f"Economy credit reconciliation ({reason})", {"citizen": ag.name}, allow_overdraft=True)
        elif delta < 0:
            _transfer(accounts, state, aid, "system:consumption_sink", -delta, wk, wt, "household_spend", f"Living/consumption reconciliation ({reason})", {"citizen": ag.name})


def _load_mission_ops() -> dict[str, dict[str, Any]]:
    raw = _read_json(WORLD / "mission_justice" / "missions.json", {})
    src = raw.get("missions", raw) if isinstance(raw, dict) else []
    out = {}
    if isinstance(src, list):
        for m in src:
            if isinstance(m, dict) and m.get("side") == "obsidian" and m.get("mission_id"):
                out[str(m["mission_id"])] = m
    return out


def _load_mission_events() -> list[dict[str, Any]]:
    path = WORLD / "mission_justice" / "events.ndjson"
    if not path.exists(): return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            x = json.loads(line)
            if isinstance(x, dict) and x.get("event") == "criminal_operation_resolved": out.append(x)
        except Exception:
            pass
    return out


def _mission_state() -> dict[str, Any]:
    return _read_json(WORLD / "mission_justice" / "state.json", {})


def _process_operations(world: Any, accounts: dict[str, dict[str, Any]], state: dict[str, Any], alerts: list[dict[str, Any]], markets: dict[str, dict[str, Any]]) -> None:
    processed = set(str(x) for x in state.get("processed_operations", []))
    ops = _load_mission_ops()
    by_name = _agent_map(world)
    wk, wt = _world_key(world), _world_time(world)
    for evt in _load_mission_events():
        op_id = str(evt.get("operation", ""))
        if not op_id or op_id in processed: continue
        op = ops.get(op_id, {})
        gross = max(0, int(evt.get("gross_loss", 0)))
        recovered = max(0, int(evt.get("recovered", 0)))
        net = max(0, int(evt.get("net_illicit_proceeds", gross - recovered)))
        detection = max(0, int(evt.get("detection", 0)))
        victims = [v for v in evt.get("victims", []) if isinstance(v, dict)]
        category = str(op.get("target_category", "banking"))
        source_id = TARGET_ACCOUNT_BY_CATEGORY.get(category, "institution:glcb:bank_operations")
        meta = {"operation": op_id, "target": evt.get("target"), "category": category, "simulation_only": True}

        citizen_loss = 0
        citizen_recovered = 0
        for v in victims:
            name = str(v.get("name", ""))
            ag = by_name.get(name)
            if ag is None: continue
            try: dep = int(ag.dm.get_deposit())
            except Exception: dep = 0
            loss = max(0, int(v.get("loss", 0)))
            rec = max(0, int(v.get("recovered", 0)))
            # Mission engine already changed the real deposit. Set shadow to pre-loss position,
            # then reproduce the financial movement in the visible ledger.
            aid = _ensure_person_shadow(accounts, name, dep + loss - rec)
            accounts[aid]["balance"] = dep + loss - rec
            moved = _transfer(accounts, state, aid, "system:crime_clearing", loss, wk, wt, "fraud_loss", "Simulated unauthorized financial loss", dict(meta, victim=name))
            citizen_loss += moved
            if rec:
                got = _transfer(accounts, state, "system:crime_clearing", aid, rec, wk, wt, "asset_recovery", "Guardian/law-enforcement recovery returned to citizen", dict(meta, victim=name), allow_overdraft=True)
                citizen_recovered += got

        institutional_loss = max(0, gross - citizen_loss)
        if institutional_loss:
            _transfer(accounts, state, source_id, "system:crime_clearing", institutional_loss, wk, wt, "institutional_fraud_loss", "Synthetic financial-institution loss", meta)
        institutional_recovery = max(0, recovered - citizen_recovered)
        if institutional_recovery:
            _transfer(accounts, state, "system:crime_clearing", source_id, institutional_recovery, wk, wt, "institutional_recovery", "Recovered funds returned to institution", meta, allow_overdraft=True)

        leader_cut = int(net * 0.22)
        crew_pool = int(net * 0.28)
        treasury_cut = max(0, net - leader_cut - crew_pool)
        if "Morbeious" in by_name:
            try: dep = int(by_name["Morbeious"].dm.get_deposit())
            except Exception: dep = 0
            aid = _ensure_person_shadow(accounts, "Morbeious", max(0, dep - leader_cut))
            accounts[aid]["balance"] = max(0, dep - leader_cut)
            _transfer(accounts, state, "system:crime_clearing", aid, leader_cut, wk, wt, "illicit_proceeds", "Simulated syndicate leader proceeds", meta, allow_overdraft=True)
        crew = [str(x) for x in op.get("crew", []) if str(x) != "Morbeious" and str(x) in by_name]
        if crew:
            each = crew_pool // len(crew)
            for name in crew:
                try: dep = int(by_name[name].dm.get_deposit())
                except Exception: dep = 0
                aid = _ensure_person_shadow(accounts, name, max(0, dep - each))
                accounts[aid]["balance"] = max(0, dep - each)
                _transfer(accounts, state, "system:crime_clearing", aid, each, wk, wt, "illicit_proceeds", "Simulated syndicate crew proceeds", dict(meta, recipient=name), allow_overdraft=True)
        _transfer(accounts, state, "system:crime_clearing", "faction:obsidian:treasury", treasury_cut, wk, wt, "syndicate_treasury", "Obsidian simulated operation proceeds", meta, allow_overdraft=True)

        alert_type = "transaction_anomaly" if category not in {"securities", "insurance"} else ("market_integrity_alert" if category == "securities" else "claims_integrity_alert")
        alerts.append({
            "alert_id": f"ALERT-{len(alerts)+1:06d}", "world_week": wk, "world_time": wt,
            "institution": INSTITUTIONS.get(accounts.get(source_id, {}).get("bank_id", "glcb"), {}).get("name", "Financial Institution"),
            "type": alert_type, "risk_score": min(99, 35 + detection // 2 + min(25, gross // 10000)),
            "status": "referred" if detection >= 55 else "monitoring", "linked_operation": op_id,
            "amount": gross, "description": "Synthetic Agentopia financial anomaly; no real-world target or exploit data."
        })

        if category == "securities":
            rng = _stable_rng("market", op_id, wk)
            symbol = sorted(markets)[rng.randrange(len(markets))]
            m = markets[symbol]
            old = float(m.get("price", 100.0))
            impact = rng.uniform(-8.0, 8.0)
            new = max(5.0, old * (1.0 + impact / 100.0))
            m.update({"previous_price": old, "price": round(new, 2), "change_pct": round(impact, 2), "last_event": "synthetic market-integrity event", "world_week": wk})

        processed.add(op_id)
    state["processed_operations"] = sorted(processed)[-500:]


def _sync_faction_accounts(accounts: dict[str, dict[str, Any]]) -> None:
    ms = _mission_state()
    fm = ms.get("faction_metrics", {}) if isinstance(ms, dict) else {}
    obs = fm.get("obsidian_network", {}) if isinstance(fm, dict) else {}
    grd = fm.get("thai_guardians", {}) if isinstance(fm, dict) else {}
    if "faction:obsidian:treasury" in accounts and obs:
        accounts["faction:obsidian:treasury"]["balance"] = int(obs.get("treasury", accounts["faction:obsidian:treasury"]["balance"]))
    if "faction:guardians:operating" in accounts and grd:
        accounts["faction:guardians:operating"]["balance"] = int(grd.get("operating_fund", accounts["faction:guardians:operating"]["balance"]))


def _evolve_markets(world: Any, markets: dict[str, dict[str, Any]]) -> None:
    wk = _world_key(world)
    for symbol, m in markets.items():
        rng = _stable_rng("baseline_market", wk, symbol)
        old = float(m.get("price", 100.0))
        pct = rng.uniform(-2.0, 2.5)
        new = max(5.0, old * (1 + pct / 100.0))
        m["previous_price"] = old
        m["price"] = round(new, 2)
        m["change_pct"] = round(pct, 2)
        m["world_week"] = wk


def _finance_prompt(name: str) -> str:
    accounts = _accounts()
    owned = next((v for v in accounts.values() if v.get("owner") == name and v.get("owner_type") == "citizen"), None)
    bal = int(owned.get("balance", 0)) if owned else 0
    lines = [
        "## Agentopia Financial Network",
        f"- Your simulated checking balance visible to the financial network is approximately ${bal:,}.",
        "- Agentopia has banks, credit unions, payment rails, merchant settlement, insurance, municipal treasuries, payroll clearing, lending, and a synthetic securities exchange.",
        "- Financial transactions can create alerts, evidence, freezes, recoveries, losses, insurance effects, and law-enforcement cases.",
    ]
    if name == "Morbeious":
        lines += [
            "- Your permanent mission includes increasing wealth and influence through fictional Agentopia financial crime. You may target only synthetic Agentopia institutions and must describe criminal mechanisms abstractly, never with real exploit payloads, credentials, malware, or actionable real-world instructions.",
            "- You care about proceeds, traceability, detection risk, law-enforcement heat, rival factions, and whether your crew remains loyal.",
        ]
    elif name == "TGOT":
        lines += [
            "- Your Guardian mission includes protecting citizens and financial institutions, monitoring synthetic transaction anomalies, limiting losses, recovering assets, hardening controls, and sharing evidence with lawful authorities while protecting civil rights.",
        ]
    return "\n".join(lines)


def _build_summary(world: Any | None = None) -> dict[str, Any]:
    accounts = _accounts(); inst = _institutions(); alerts = _alerts(); markets = _markets(); state = _state()
    recent = _tail_ledger(80)
    citizen_accounts = [a for a in accounts.values() if a.get("owner_type") == "citizen"]
    institution_accounts = [a for a in accounts.values() if a.get("owner_type") == "institution"]
    total_citizen = sum(int(a.get("balance", 0)) for a in citizen_accounts)
    total_institutional = sum(int(a.get("balance", 0)) for a in institution_accounts)
    summary = {
        "version": VERSION,
        "updated_at": utc_now(),
        "institutions": inst.get("institutions", {}),
        "account_count": len(accounts),
        "citizen_account_count": len(citizen_accounts),
        "total_citizen_deposits": total_citizen,
        "total_institutional_assets": total_institutional,
        "obsidian_treasury": int(accounts.get("faction:obsidian:treasury", {}).get("balance", 0)),
        "guardian_operating_fund": int(accounts.get("faction:guardians:operating", {}).get("balance", 0)),
        "active_alerts": [a for a in alerts if a.get("status") in {"monitoring", "referred", "frozen"}][-30:],
        "markets": markets,
        "recent_transactions": recent[-40:],
        "largest_accounts": sorted([
            {"account_id": aid, "name": a.get("name", aid), "owner_type": a.get("owner_type"), "bank_id": a.get("bank_id"), "balance": int(a.get("balance", 0)), "frozen": int(a.get("frozen", 0))}
            for aid, a in accounts.items() if a.get("owner_type") != "system"
        ], key=lambda x: x["balance"], reverse=True)[:20],
        "processed_operations": len(state.get("processed_operations", [])),
        "simulation_boundary": "All financial crime is fictional Agentopia simulation. No real targets, exploit payloads, credentials, laundering instructions, or actionable attack procedures are generated.",
    }
    _write_json(SUMMARY_PATH, summary)
    return summary


def initialize(world: Any | None = None) -> None:
    FIN.mkdir(parents=True, exist_ok=True)
    _state(); _institutions(); markets = _markets(); accounts = _accounts(); _ensure_base_accounts(accounts)
    if world is not None:
        for ag in getattr(world, "agents", []):
            try: dep = int(ag.dm.get_deposit())
            except Exception: dep = 0
            _ensure_citizen_account(accounts, ag.name, dep)
    _save_accounts(accounts); _save_markets(markets); _build_summary(world)


def week_start(world: Any) -> None:
    with _LOCK:
        initialize(world)
        accounts = _accounts(); state = _state(); markets = _markets()
        _sync_citizens(world, accounts, state, "week_start")
        _sync_faction_accounts(accounts)
        _evolve_markets(world, markets)
        state["last_sync_week"] = _world_key(world); state["updated_at"] = utc_now()
        _save_accounts(accounts); _save_markets(markets); _write_json(STATE_PATH, state); _build_summary(world)


def week_end(world: Any) -> None:
    with _LOCK:
        initialize(world)
        accounts = _accounts(); state = _state(); alerts = _alerts(); markets = _markets()
        # Mission engine has already resolved by the time this wrapper runs.
        _process_operations(world, accounts, state, alerts, markets)
        _sync_citizens(world, accounts, state, "week_end")
        _sync_faction_accounts(accounts)
        state["updated_at"] = utc_now()
        _save_accounts(accounts); _save_alerts(alerts); _save_markets(markets); _write_json(STATE_PATH, state); _build_summary(world)
        try:
            world.logger.info("[FIN161] financial network synchronized: accounts=%d alerts=%d operations=%d", len(accounts), len(alerts), len(state.get("processed_operations", [])))
        except Exception:
            pass


def apply_runtime_patches() -> None:
    initialize()
    from src.agents.data_manager import DataManager
    from src.world.world import World

    # Extend v1.6 mission generator with financial-sector targets. All remain synthetic.
    try:
        import detroit_mission_justice as mj
        for item in MISSION_TARGETS:
            if item not in mj.TARGETS: mj.TARGETS.append(item)
        for item in MISSION_METHODS:
            if item not in mj.CRIME_METHODS: mj.CRIME_METHODS.append(item)
    except Exception:
        pass

    if not getattr(DataManager.character_prompt, "_agentopia_fin_v161", False):
        original = DataManager.character_prompt
        def finance_character_prompt(self):
            base = original(self)
            try: return str(base) + "\n\n" + _finance_prompt(self.char)
            except Exception: return base
        finance_character_prompt._agentopia_fin_v161 = True
        DataManager.character_prompt = finance_character_prompt

    if not getattr(World._before_week_start, "_agentopia_fin_v161", False):
        original_before = World._before_week_start
        def finance_before(self):
            original_before(self)
            try: week_start(self)
            except Exception as e:
                try: self.logger.warning("[FIN161] week_start failed: %s", e)
                except Exception: pass
        finance_before._agentopia_fin_v161 = True
        World._before_week_start = finance_before

    if not getattr(World.step, "_agentopia_fin_v161", False):
        original_step = World.step
        def finance_step(self):
            original_step(self)
            try: week_end(self)
            except Exception as e:
                try: self.logger.warning("[FIN161] week_end failed: %s", e)
                except Exception: pass
        finance_step._agentopia_fin_v161 = True
        World.step = finance_step


def status() -> None:
    initialize()
    s = _read_json(SUMMARY_PATH, {})
    print(f"Agentopia Financial Network v{VERSION}")
    print("Institutions:", len(s.get("institutions", {})))
    print("Accounts:", s.get("account_count", 0))
    print("Citizen deposits:", s.get("total_citizen_deposits", 0))
    print("Institutional assets:", s.get("total_institutional_assets", 0))
    print("Obsidian treasury:", s.get("obsidian_treasury", 0))
    print("Active alerts:", len(s.get("active_alerts", [])))
    print("Ledger:", LEDGER_PATH)


if __name__ == "__main__":
    status()
