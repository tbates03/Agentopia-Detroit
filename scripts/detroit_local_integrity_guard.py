#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP = Path(os.environ.get("AGENTOPIA_HOME", str(Path.home() / "AI" / "Agentopia"))).expanduser()
WORLD = APP / "data" / "detroit_persistent"
FIN = WORLD / "finance"

TERMINAL = {"contained", "resolved", "closed", "recovered", "partially_recovered"}
CONTAINED_OPS = {
    "OBS-2045-01-4579",
    "OBS-2045-02-1445",
    "OBS-2045-03-5421",
    "OBS-2045-04-5516",
}
KNOWN_RECOVERY = 60220

# STRICT current-geography / clearly NYC-institution terms only.
# Deliberately does NOT match bare "New York", so names such as
# "New York Magazine" do not become geography violations.
BAD_CURRENT_GEO = re.compile(
    r"\b("
    r"new york city|nyc|new york university|new york public library|"
    r"manhattan|brooklyn|bronx|queens|staten island|long island city|"
    r"greenwich village|west village|east village|bleecker street|"
    r"park avenue|flatiron district|soho|jersey city|new jersey|"
    r"nypd|fdny|columbia university"
    r")\b",
    re.IGNORECASE,
)

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def atomic_save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)

def same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
        b, sort_keys=True, ensure_ascii=False
    )

def account_text(rec: dict[str, Any]) -> str:
    fields = (
        "account_id", "name", "owner", "business_id", "business_name",
        "company", "employer", "organization", "location", "address",
        "headquarters",
    )
    return " | ".join(str(rec.get(k) or "") for k in fields)

def enforce_alerts() -> dict[str, int]:
    alerts_path = FIN / "alerts.json"
    summary_path = FIN / "summary.json"

    alerts_doc = load(alerts_path, {"alerts": []})
    alerts = alerts_doc.get("alerts", []) if isinstance(alerts_doc, dict) else []
    if not isinstance(alerts, list):
        alerts = []

    original_alerts = json.loads(json.dumps(alerts))
    for a in alerts:
        if not isinstance(a, dict):
            continue
        if str(a.get("linked_operation") or "") in CONTAINED_OPS:
            a["status"] = "contained"
            a["historical"] = True
            a["resolution"] = "guardian_contained"
            a.setdefault("contained_at", now())

    if not same(original_alerts, alerts):
        alerts_doc["alerts"] = alerts
        alerts_doc["updated_at"] = now()
        alerts_doc["lifecycle_version"] = "local-detroit-2"
        atomic_save(alerts_path, alerts_doc)

    active = [
        a for a in alerts
        if isinstance(a, dict)
        and str(a.get("status") or "").lower() not in TERMINAL
    ]
    historical = [
        a for a in alerts
        if isinstance(a, dict)
        and str(a.get("status") or "").lower() in TERMINAL
    ]
    exposure = sum(int(a.get("amount") or 0) for a in alerts if isinstance(a, dict))
    recovered = min(KNOWN_RECOVERY, exposure)
    unrecovered = max(0, exposure - recovered)

    summary = load(summary_path, {})
    if not isinstance(summary, dict):
        summary = {}
    desired = dict(summary)
    desired.update({
        "active_alerts": active,
        "active_alert_count": len(active),
        "historical_alerts": historical,
        "historical_alert_count": len(historical),
        "contained_alert_count": sum(
            1 for a in historical if str(a.get("status") or "").lower() == "contained"
        ),
        "alert_total_exposure": exposure,
        "guardian_recovered_total": recovered,
        "unrecovered_exposure": unrecovered,
        "alert_lifecycle_version": "local-detroit-2",
    })
    if not same(summary, desired):
        desired["alert_lifecycle_updated_at"] = now()
        atomic_save(summary_path, desired)

    return {
        "alerts_total": len(alerts),
        "active": len(active),
        "contained": len(historical),
        "exposure": exposure,
        "recovered": recovered,
        "unrecovered": unrecovered,
    }

def enforce_finance_geography() -> tuple[int, set[str]]:
    path = FIN / "accounts.json"
    doc = load(path, {"accounts": {}})
    accounts = doc.get("accounts", {}) if isinstance(doc, dict) else {}
    if not isinstance(accounts, dict):
        accounts = {}

    original = json.loads(json.dumps(accounts))
    qids: set[str] = set()

    for aid, rec in accounts.items():
        if not isinstance(rec, dict) or rec.get("owner_type") != "business":
            continue
        m = BAD_CURRENT_GEO.search(account_text(rec))
        if not m:
            continue
        qids.add(str(aid))
        rec["frozen"] = 1
        rec["status"] = "quarantined_geography"
        rec["geography_quarantined"] = True
        rec["quarantine_reason"] = (
            f"current geography outside Detroit/Metro Detroit: {m.group(0)}"
        )
        rec.setdefault("quarantined_at", now())

    if not same(original, accounts):
        doc["accounts"] = accounts
        doc["updated_at"] = now()
        doc["geography_guard_version"] = "local-detroit-2"
        atomic_save(path, doc)

    return len(qids), qids

def enforce_business_state() -> tuple[int, list[str]]:
    changed_records = 0
    changed_files: list[str] = []

    def walk(x: Any) -> int:
        changed = 0
        if isinstance(x, dict):
            looks_business = any(
                k in x for k in (
                    "business_id", "business_name", "employer", "company",
                    "operating", "revenue", "payroll", "employees",
                )
            )
            if looks_business:
                sample = account_text(x)
                m = BAD_CURRENT_GEO.search(sample)
                if m and not (
                    x.get("status") == "quarantined_geography"
                    and x.get("geography_quarantined") is True
                ):
                    x["status"] = "quarantined_geography"
                    x["operating"] = False
                    x["geography_quarantined"] = True
                    x["quarantine_reason"] = (
                        f"current geography outside Detroit/Metro Detroit: {m.group(0)}"
                    )
                    x.setdefault("quarantined_at", now())
                    changed += 1
            for v in x.values():
                changed += walk(v)
        elif isinstance(x, list):
            for v in x:
                changed += walk(v)
        return changed

    for path in (
        WORLD / "business_economy" / "summary.json",
        WORLD / "business_economy" / "state.json",
        WORLD / "business_economy" / "openings.json",
    ):
        if not path.exists():
            continue
        data = load(path, None)
        if data is None:
            continue
        before = json.loads(json.dumps(data))
        n = walk(data)
        if n and not same(before, data):
            atomic_save(path, data)
            changed_records += n
            changed_files.append(str(path))

    return changed_records, changed_files

def clean_summary(qids: set[str]) -> None:
    path = FIN / "summary.json"
    summary = load(path, {})
    if not isinstance(summary, dict):
        return
    before = json.loads(json.dumps(summary))

    # Remove quarantined business accounts from "live/current" list views.
    for key, value in list(summary.items()):
        if isinstance(value, list):
            summary[key] = [
                item for item in value
                if not (
                    isinstance(item, dict)
                    and str(item.get("account_id") or "") in qids
                )
            ]

    summary["geography_quarantined_accounts"] = len(qids)
    summary["geography_guard_version"] = "local-detroit-2"
    if not same(before, summary):
        summary["geography_guard_updated_at"] = now()
        atomic_save(path, summary)

def report(alerts: dict[str, int], qcount: int, bcount: int, bfiles: list[str]) -> None:
    path = WORLD / "governance" / "local_integrity_report.json"
    payload = {
        "updated_at": now(),
        "version": "local-detroit-2",
        "alerts": alerts,
        "finance_accounts_quarantined": qcount,
        "business_records_quarantined_this_run": bcount,
        "business_files_changed_this_run": bfiles,
        "policy": {
            "current_geography": "Detroit/Metro Detroit",
            "bare_new_york_is_not_a_location_violation": True,
            "historical_origin_preserved": True,
            "finance_ledger_rewritten": False,
        },
    }
    atomic_save(path, payload)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    alerts = enforce_alerts()
    qcount, qids = enforce_finance_geography()
    bcount, bfiles = enforce_business_state()
    clean_summary(qids)
    report(alerts, qcount, bcount, bfiles)

    if not args.quiet:
        print(json.dumps({
            "alerts": alerts,
            "finance_accounts_quarantined": qcount,
            "business_records_quarantined_this_run": bcount,
            "business_files_changed_this_run": bfiles,
        }, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
