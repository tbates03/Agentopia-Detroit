#!/usr/bin/env python3
"""Opt-in, disk-backed episodic recall for Agentopia Detroit.

Canonical persona JSONL files remain authoritative. SQLite is a disposable,
rebuildable index, not macOS swap and not a replacement for model RAM/KV cache.
All data stays in data/detroit_persistent/cognition (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = Path(os.environ.get('AGENTOPIA_MEMORY_WORLD', ROOT / 'data' / 'detroit_persistent'))
MAX_EPISODE = 800
MAX_LINES = 2000
SCAN_BYTES = 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def faction_for(world: Path, agent: str) -> str:
    try:
        doc = json.loads((world / 'factions.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    factions = doc.get('factions', doc) if isinstance(doc, dict) else {}
    for key, record in factions.items() if isinstance(factions, dict) else []:
        if isinstance(record, dict) and agent in [str(x) for x in record.get('members', [])] + [str(record.get('leader', ''))]:
            return str(record.get('name') or key)
    return ''


def _clean(value: Any, limit: int = MAX_EPISODE) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return re.sub(r'\s+', ' ', value).strip()[:limit]


class EpisodicMemory:
    def __init__(self, world: Path = WORLD):
        self.world = Path(world)
        self.db = self.world / 'cognition' / 'episodic_memory.sqlite3'
        self._initialized = False

    def _connect(self, create: bool = False) -> sqlite3.Connection | None:
        if not create and not self.db.exists():
            return None
        if create:
            self.db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db, timeout=1.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=1000')
        if create and not self._initialized:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    visibility TEXT NOT NULL CHECK (visibility IN ('agent','faction','public')),
                    audience TEXT NOT NULL,
                    importance INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_episode_acl
                    ON episodes(visibility, audience, recorded_at DESC);
                CREATE TABLE IF NOT EXISTS ingest_cursor (
                    source TEXT PRIMARY KEY, inode INTEGER NOT NULL, position INTEGER NOT NULL
                );
            ''')
            try:
                conn.executescript('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                        summary, content='episodes', content_rowid='rowid'
                    );
                    CREATE TRIGGER IF NOT EXISTS episode_ai AFTER INSERT ON episodes BEGIN
                        INSERT INTO episodes_fts(rowid,summary) VALUES(new.rowid,new.summary);
                    END;
                    CREATE TRIGGER IF NOT EXISTS episode_ad AFTER DELETE ON episodes BEGIN
                        INSERT INTO episodes_fts(episodes_fts,rowid,summary)
                        VALUES('delete',old.rowid,old.summary);
                    END;
                ''')
            except sqlite3.OperationalError:
                pass  # Standard indexed recency query still works without FTS5.
            self._initialized = True
        return conn

    def _put(self, conn: sqlite3.Connection, *, event_id: str, category: str,
             visibility: str, audience: str, summary: str, source: str,
             occurred_at: str = '', importance: int = 50) -> bool:
        if visibility not in ('agent', 'faction', 'public'):
            raise ValueError('Invalid memory visibility')
        if visibility != 'public' and not audience:
            raise ValueError('Private memory requires a named audience')
        summary = _clean(summary)
        if not summary:
            return False
        mid = hashlib.sha256(f'{event_id}\0{visibility}\0{audience}'.encode('utf-8')).hexdigest()
        result = conn.execute('''
            INSERT OR IGNORE INTO episodes
            (id,recorded_at,occurred_at,category,visibility,audience,importance,summary,source)
            VALUES(?,?,?,?,?,?,?,?,?)
        ''', (mid, _now(), _clean(occurred_at, 90), category, visibility,
              audience if visibility != 'public' else '', max(0,min(100,int(importance))), summary, source))
        return result.rowcount == 1

    def remember(self, *, event_id: str, category: str, visibility: str,
                 audience: str, summary: str, occurred_at: str = '',
                 importance: int = 50, source: str = 'explicit') -> bool:
        conn = self._connect(create=True)
        assert conn is not None
        try:
            added = self._put(conn, event_id=event_id, category=category,
                              visibility=visibility, audience=audience, summary=summary,
                              occurred_at=occurred_at, importance=importance, source=source)
            conn.commit()
            return added
        finally:
            conn.close()

    def _visible(self, conn: sqlite3.Connection, agent: str, query: str,
                 limit: int) -> list[sqlite3.Row]:
        faction = faction_for(self.world, agent)  # Never trust a caller-supplied faction.
        acl = "(e.visibility='public' OR (e.visibility='agent' AND e.audience=?) OR (e.visibility='faction' AND e.audience=?))"
        params = [agent, faction]
        words = re.findall(r'[A-Za-z0-9]{3,32}', query.lower())[:8]
        if words:
            match = ' OR '.join('"' + word + '"' for word in words)
            try:
                return conn.execute(
                    f'''SELECT e.* FROM episodes_fts f JOIN episodes e ON e.rowid=f.rowid
                    WHERE episodes_fts MATCH ? AND {acl}
                    ORDER BY bm25(episodes_fts), e.recorded_at DESC LIMIT ?''',
                    [match, *params, limit]).fetchall()
            except sqlite3.OperationalError:
                pass
        return conn.execute(
            f'''SELECT e.* FROM episodes e WHERE {acl}
                ORDER BY e.recorded_at DESC, e.rowid DESC LIMIT ?''',
            [*params, min(128, limit if not words else max(64, limit))]).fetchall()

    def recall(self, agent: str, query: str = '', limit: int = 4,
               max_chars: int = 620) -> list[dict[str, Any]]:
        if not agent or limit < 1 or max_chars < 1:
            return []
        conn = self._connect()
        if conn is None:
            return []
        try:
            rows = self._visible(conn, agent, query, min(12, limit))
            out: list[dict[str, Any]] = []
            remaining = max_chars
            for row in rows:
                summary = str(row['summary'])[:remaining]
                if not summary:
                    break
                out.append({'category': row['category'], 'summary': summary,
                            'occurred_at': row['occurred_at'], 'visibility': row['visibility']})
                remaining -= len(summary)
                if remaining <= 0:
                    break
            return out
        finally:
            conn.close()

    def _ingest_event(self, conn: sqlite3.Connection, path: Path, event: dict[str, Any], digest: str,
                      owner: str = '') -> int:
        source = str(path.relative_to(self.world))
        t = str(event.get('time') or '')
        if owner:
            content = event.get('content', event.get('summary', ''))
            if not content:
                return 0
            return int(self._put(conn, event_id=digest, category='weekly_diary',
                                 visibility='agent', audience=owner, summary=_clean(content),
                                 occurred_at=t, importance=55, source=source))
        if path.name == 'cyber_events.jsonl':
            threat = _clean(event.get('threat', 'cyber event'), 80)
            target = _clean(event.get('target', 'simulated infrastructure'), 80)
            result = _clean(event.get('result', 'unknown'), 40)
            n = int(self._put(conn, event_id=digest, category='simulated_operation',
                              visibility='faction', audience='Obsidian Network',
                              summary=f'Simulated {threat} operation on {target}: {result}.',
                              occurred_at=t, importance=75, source=source))
            if event.get('detected') is True:
                n += int(self._put(conn, event_id=digest, category='detected_incident',
                                   visibility='faction', audience='ThAI Guardians',
                                   summary=f'Detected simulated {threat} activity at {target}: {result}.',
                                   occurred_at=t, importance=85, source=source))
            if result == 'success' and event.get('impact'):
                n += int(self._put(conn, event_id=digest, category='public_disruption',
                                   visibility='public', audience='',
                                   summary=f'Reported fictional service impact near {target}.',
                                   occurred_at=t, importance=70, source=source))
            return n
        if path.name == 'audit_events.jsonl':
            target = _clean(event.get('target', 'simulated infrastructure'), 80)
            controls = ', '.join(_clean(x, 50) for x in (event.get('improved_controls') or [])[:6])
            return int(self._put(conn, event_id=digest, category='guardian_audit',
                                 visibility='faction', audience='ThAI Guardians',
                                 summary=f'Purple-team review at {target}; controls: {controls or "review logged"}.',
                                 occurred_at=t, importance=80, source=source))
        return 0

    def ingest(self, path: Path, owner: str = '') -> dict[str, int]:
        path = Path(path)
        if not path.is_file() or not path.resolve().is_relative_to(self.world.resolve()):
            return {'read': 0, 'added': 0, 'pending': 0}
        expected = (self.world / 'persona' / owner / 'memory' / 'weekly_diary.jsonl') if owner else (self.world / 'digital_twin' / path.name)
        if path.resolve() != expected.resolve() or (not owner and path.name not in ('cyber_events.jsonl', 'audit_events.jsonl')):
            raise ValueError('Memory source/audience does not match its trusted world path')
        key = str(path.relative_to(self.world))
        conn = self._connect(create=True)
        assert conn is not None
        try:
            info = path.stat()
            cursor = conn.execute('SELECT inode,position FROM ingest_cursor WHERE source=?', (key,)).fetchone()
            start = int(cursor['position']) if cursor and int(cursor['inode']) == info.st_ino and int(cursor['position']) <= info.st_size else max(0, info.st_size - SCAN_BYTES)
            count = added = 0
            with path.open('rb') as f:
                f.seek(start)
                if start and (cursor is None or int(cursor['inode']) != info.st_ino or int(cursor['position']) > info.st_size):
                    f.readline()  # Initial tail scan starts at a partial line.
                position = f.tell()
                while count < MAX_LINES and f.tell() - start < SCAN_BYTES:
                    raw = f.readline()
                    if not raw or not raw.endswith(b'\n'):
                        break  # Never index a partially written record.
                    position = f.tell()
                    count += 1
                    try:
                        event = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    digest = hashlib.sha256(key.encode('utf-8') + b'\0' + raw.rstrip(b'\r\n')).hexdigest()
                    added += self._ingest_event(conn, path, event, digest, owner)
            conn.execute('''INSERT INTO ingest_cursor(source,inode,position) VALUES(?,?,?)
                            ON CONFLICT(source) DO UPDATE SET inode=excluded.inode, position=excluded.position''',
                         (key, info.st_ino, position))
            conn.commit()
            return {'read': count, 'added': added, 'pending': int(position < info.st_size)}
        finally:
            conn.close()

    def sync(self, agents: list[str]) -> dict[str, int]:
        paths = [(self.world / 'digital_twin' / name, '') for name in ('cyber_events.jsonl', 'audit_events.jsonl')]
        # The persistent world already restricts the expensive AI cohort.
        paths += [(self.world / 'persona' / name / 'memory' / 'weekly_diary.jsonl', name)
                  for name in sorted(set(agents)) if name not in ('.', '..') and '/' not in name and '\\' not in name]
        result = {'sources': 0, 'read': 0, 'added': 0, 'pending': 0}
        for path, owner in paths:
            if not path.exists():
                continue
            part = self.ingest(path, owner=owner)
            result['sources'] += 1
            for field in ('read', 'added', 'pending'):
                result[field] += part[field]
        return result

    def stats(self) -> dict[str, Any]:
        if not self.db.exists():
            return {'episodes': 0, 'bytes': 0, 'database': str(self.db)}
        conn = self._connect()
        assert conn is not None
        try:
            n = conn.execute('SELECT COUNT(*) FROM episodes').fetchone()[0]
            kinds = dict(conn.execute('SELECT category,COUNT(*) FROM episodes GROUP BY category').fetchall())
        finally:
            conn.close()
        size = sum(p.stat().st_size for p in (self.db, Path(str(self.db) + '-wal'), Path(str(self.db) + '-shm')) if p.exists())
        return {'episodes': n, 'bytes': size, 'by_category': kinds, 'database': str(self.db)}


def main() -> None:
    p = argparse.ArgumentParser(description='Agentopia Detroit opt-in disk-backed episodic memory')
    p.add_argument('command', choices=['status', 'bootstrap', 'recall'])
    p.add_argument('--agent', default='')
    p.add_argument('--query', default='')
    args = p.parse_args()
    store = EpisodicMemory()
    if args.command == 'bootstrap':
        root = store.world / '.active_persona_view'
        if not root.exists():
            root = store.world / 'persona'
        names = [x.name for x in root.iterdir() if x.is_dir() or x.is_symlink()] if root.exists() else []
        print(json.dumps(store.sync(names), indent=2))
    elif args.command == 'recall':
        if not args.agent:
            p.error('--agent is required for recall')
        print(json.dumps(store.recall(args.agent, args.query), indent=2))
    else:
        print(json.dumps(store.stats(), indent=2))


if __name__ == '__main__':
    main()
