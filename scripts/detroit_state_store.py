#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
DEFAULT_DB = WORLD / "civilization.sqlite3"
SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS citizens (
            citizen_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            alive INTEGER NOT NULL DEFAULT 1,
            birth_year INTEGER,
            life_stage TEXT,
            origin_type TEXT,
            origin_text TEXT,
            founder_ids_json TEXT NOT NULL DEFAULT '[]',
            is_persona INTEGER NOT NULL DEFAULT 0,
            promoted_year INTEGER,
            source TEXT NOT NULL DEFAULT 'legacy_json',
            updated_at TEXT NOT NULL
        );
        DROP INDEX IF EXISTS idx_citizens_name;
        CREATE INDEX IF NOT EXISTS idx_citizens_name ON citizens(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_citizens_persona_alive ON citizens(is_persona, alive);
        CREATE INDEX IF NOT EXISTS idx_citizens_life_stage ON citizens(life_stage);

        CREATE TABLE IF NOT EXISTS entity_state (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            state_json TEXT NOT NULL,
            state_hash TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(entity_type, entity_id)
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            sim_year INTEGER,
            sim_week INTEGER,
            subject_id TEXT,
            actor_id TEXT,
            source TEXT NOT NULL,
            importance REAL NOT NULL DEFAULT 1.0,
            payload_json TEXT NOT NULL DEFAULT '{}',
            dedupe_key TEXT UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_events_subject_time ON events(subject_id, sim_year DESC, sim_week DESC);
        CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, sim_year DESC, sim_week DESC);
        CREATE INDEX IF NOT EXISTS idx_events_importance ON events(importance DESC);

        CREATE TABLE IF NOT EXISTS activation_scores (
            citizen_id TEXT PRIMARY KEY,
            score REAL NOT NULL,
            reasons_json TEXT NOT NULL,
            scored_at TEXT NOT NULL,
            sim_year INTEGER,
            FOREIGN KEY(citizen_id) REFERENCES citizens(citizen_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_activation_score ON activation_scores(score DESC);
        """
    )
    conn.execute(
        "INSERT INTO meta(key,value,updated_at) VALUES('schema_version',?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(SCHEMA_VERSION), utc_now()),
    )
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _founder_ids(person: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if person.get("founder_id"):
        out.append(str(person["founder_id"]))
    lineage = person.get("lineage")
    if isinstance(lineage, dict):
        out.extend(str(x) for x in lineage.get("founder_ids", []) if x)
    return sorted(set(out))


def lifecycle_person_id_for_name(name: str) -> str:
    """Return the canonical lifecycle ID used for existing persona names."""
    return "P-" + hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12].upper()


def resolve_persona_citizen(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """Resolve a persona name without treating display names as civic identities.

    Existing lifecycle-seeded personas use a deterministic ID derived from the
    persona directory name. If that row is unavailable, prefer a row already
    marked as a persona, then a persona/profile source, then a living citizen,
    with citizen_id as the stable deterministic tie-breaker.
    """
    canonical = lifecycle_person_id_for_name(name)
    row = conn.execute(
        """
        SELECT citizen_id,name,alive,is_persona,promoted_year,source
        FROM citizens
        WHERE citizen_id=? AND name=? COLLATE NOCASE
        """,
        (canonical, name),
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """
        SELECT citizen_id,name,alive,is_persona,promoted_year,source
        FROM citizens
        WHERE name=? COLLATE NOCASE
        ORDER BY is_persona DESC,
                 CASE WHEN source='persona/profile' THEN 0 ELSE 1 END,
                 alive DESC,
                 citizen_id ASC
        LIMIT 1
        """,
        (name,),
    ).fetchone()


def upsert_citizen(conn: sqlite3.Connection, citizen_id: str, person: dict[str, Any], *, source: str) -> None:
    name = str(person.get("name") or citizen_id).strip()
    origin_record = person.get("origin_record") if isinstance(person.get("origin_record"), dict) else {}
    origin = person.get("origin")
    if isinstance(origin, dict):
        origin_type = str(origin.get("category") or person.get("origin_type") or "resident")
        origin_text = str(origin.get("description") or origin.get("city") or "")
    else:
        origin_type = str(person.get("origin_type") or origin_record.get("category") or "resident")
        origin_text = str(origin or origin_record.get("description") or "")
    birth_year = person.get("birth_year")
    try:
        birth_year = int(birth_year) if birth_year is not None else None
    except Exception:
        birth_year = None
    promoted_year = person.get("promoted_year")
    try:
        promoted_year = int(promoted_year) if promoted_year is not None else None
    except Exception:
        promoted_year = None
    is_persona = int(bool(person.get("agentopia_persona") or person.get("is_persona") or promoted_year))
    conn.execute(
        """
        INSERT INTO citizens(
            citizen_id,name,alive,birth_year,life_stage,origin_type,origin_text,
            founder_ids_json,is_persona,promoted_year,source,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(citizen_id) DO UPDATE SET
            name=excluded.name, alive=excluded.alive, birth_year=COALESCE(excluded.birth_year,citizens.birth_year),
            life_stage=COALESCE(excluded.life_stage,citizens.life_stage), origin_type=excluded.origin_type,
            origin_text=excluded.origin_text, founder_ids_json=excluded.founder_ids_json,
            is_persona=MAX(citizens.is_persona,excluded.is_persona),
            promoted_year=COALESCE(citizens.promoted_year,excluded.promoted_year),
            source=excluded.source, updated_at=excluded.updated_at
        """,
        (
            citizen_id,
            name,
            int(bool(person.get("alive", True))),
            birth_year,
            str(person.get("life_stage") or ""),
            origin_type,
            origin_text,
            _json(_founder_ids(person)),
            is_persona,
            promoted_year,
            source,
            utc_now(),
        ),
    )


def upsert_entity_state(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: str,
    state: Any,
    *,
    source: str,
) -> None:
    raw = _json(state)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO entity_state(entity_type,entity_id,state_json,state_hash,source,updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(entity_type,entity_id) DO UPDATE SET
            state_json=excluded.state_json,state_hash=excluded.state_hash,
            source=excluded.source,updated_at=excluded.updated_at
        """,
        (entity_type, entity_id, raw, digest, source, utc_now()),
    )


def append_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    sim_year: int | None = None,
    sim_week: int | None = None,
    subject_id: str | None = None,
    actor_id: str | None = None,
    payload: dict[str, Any] | None = None,
    source: str = "agentopia",
    importance: float = 1.0,
    dedupe_key: str | None = None,
    occurred_at: str | None = None,
) -> str:
    payload = payload or {}
    occurred_at = occurred_at or utc_now()
    seed = dedupe_key or "|".join(
        [event_type, str(sim_year), str(sim_week), str(subject_id), str(actor_id), _json(payload), occurred_at]
    )
    event_id = "EVT-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        INSERT OR IGNORE INTO events(
            event_id,event_type,occurred_at,sim_year,sim_week,subject_id,actor_id,
            source,importance,payload_json,dedupe_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            event_type,
            occurred_at,
            sim_year,
            sim_week,
            subject_id,
            actor_id,
            source,
            float(importance),
            _json(payload),
            dedupe_key,
        ),
    )
    return event_id


def _persona_profile(persona_dir: Path) -> dict[str, Any]:
    profiles = persona_dir / "profile"
    files = sorted(profiles.glob("year=*.json")) if profiles.exists() else []
    if not files:
        return {"name": persona_dir.name, "is_persona": True}
    latest = max(files, key=lambda p: int(p.stem.split("=", 1)[1]) if "=" in p.stem else 0)
    profile = read_json(latest, {})
    if not isinstance(profile, dict):
        profile = {}
    profile = dict(profile)
    profile.setdefault("name", persona_dir.name)
    profile["is_persona"] = True
    return profile


def sync_legacy_state(world: Path | None = None, db_path: Path | str | None = None) -> dict[str, Any]:
    world = Path(world or WORLD)
    conn = connect(db_path or (world / "civilization.sqlite3"))
    people_path = world / "humanity" / "people.json"
    people = read_json(people_path, {})
    persona_root = world / "persona"
    cp = read_json(world / "checkpoint.json", {})
    year = int(cp.get("year", 2045)) if isinstance(cp, dict) else 2045
    week = int(cp.get("week", 1)) if isinstance(cp, dict) else 1
    civic_count = 0
    persona_count = 0

    with transaction(conn):
        if isinstance(people, dict):
            for pid, person in people.items():
                if not isinstance(person, dict):
                    continue
                upsert_citizen(conn, str(pid), person, source="humanity/people.json")
                civic_count += 1

        if persona_root.exists():
            for pdir in sorted((p for p in persona_root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
                profile = _persona_profile(pdir)
                row = resolve_persona_citizen(conn, pdir.name)
                cid = str(row["citizen_id"]) if row else "persona:" + hashlib.sha256(pdir.name.casefold().encode()).hexdigest()[:20]
                profile["agentopia_persona"] = True
                upsert_citizen(conn, cid, profile, source="persona/profile")
                persona_count += 1

        for entity_type, filename in (
            ("checkpoint", "checkpoint.json"),
            ("factions", "factions.json"),
            ("persistent_world", "persistent_world.json"),
            ("config", "config.json"),
        ):
            value = read_json(world / filename, None)
            if value is not None:
                upsert_entity_state(conn, entity_type, entity_type, value, source=filename)

        append_event(
            conn,
            "state_index_synced",
            sim_year=year,
            sim_week=week,
            payload={"civic_records": civic_count, "persona_records": persona_count},
            source="detroit_state_store",
            importance=0.25,
            dedupe_key=f"state-index-sync:{year}:{week}:{civic_count}:{persona_count}",
        )

    stats = store_stats(conn)
    conn.close()
    return stats


def store_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def scalar(sql: str) -> int:
        row = conn.execute(sql).fetchone()
        return int(row[0] or 0)

    return {
        "schema_version": SCHEMA_VERSION,
        "citizens": scalar("SELECT COUNT(*) FROM citizens"),
        "living_citizens": scalar("SELECT COUNT(*) FROM citizens WHERE alive=1"),
        "personas": scalar("SELECT COUNT(*) FROM citizens WHERE is_persona=1"),
        "events": scalar("SELECT COUNT(*) FROM events"),
        "entity_snapshots": scalar("SELECT COUNT(*) FROM entity_state"),
        "activation_scores": scalar("SELECT COUNT(*) FROM activation_scores"),
    }


def bulk_seed_citizens(conn: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        INSERT INTO citizens(citizen_id,name,alive,birth_year,life_stage,origin_type,origin_text,
        founder_ids_json,is_persona,promoted_year,source,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(citizen_id) DO NOTHING
        """,
        rows,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Agentopia Detroit indexed civilization state + event ledger")
    ap.add_argument("command", choices=["sync", "stats", "event"])
    ap.add_argument("--db", type=Path)
    ap.add_argument("--type", dest="event_type")
    ap.add_argument("--subject")
    ap.add_argument("--year", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--importance", type=float, default=1.0)
    ap.add_argument("--payload", default="{}")
    args = ap.parse_args()

    if args.command == "sync":
        print(json.dumps(sync_legacy_state(db_path=args.db), indent=2))
        return 0

    conn = connect(args.db)
    if args.command == "stats":
        print(json.dumps(store_stats(conn), indent=2))
        conn.close()
        return 0

    if not args.event_type:
        ap.error("event requires --type")
    try:
        payload = json.loads(args.payload)
    except Exception as exc:
        ap.error(f"invalid --payload JSON: {exc}")
    with transaction(conn):
        eid = append_event(
            conn,
            args.event_type,
            sim_year=args.year,
            sim_week=args.week,
            subject_id=args.subject,
            payload=payload,
            importance=args.importance,
            source="cli",
        )
    print(eid)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
