"""SQLite storage (aiosqlite, WAL). Parameterised SQL only. Ledger rows are append-only: triggers refuse
UPDATE and DELETE on ``entries`` so even a bug in the app cannot rewrite history."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiosqlite

from .core.canon import canonical

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, lang TEXT NOT NULL DEFAULT 'uz', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pairs (pair TEXT PRIMARY KEY, a INTEGER NOT NULL, b INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS pairs_a ON pairs(a);
CREATE INDEX IF NOT EXISTS pairs_b ON pairs(b);
CREATE TABLE IF NOT EXISTS entries (
  pair TEXT NOT NULL, seq INTEGER NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY (pair, seq)
);
CREATE TRIGGER IF NOT EXISTS entries_no_update BEFORE UPDATE ON entries
  BEGIN SELECT RAISE(ABORT, 'ledger entries are append-only'); END;
CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries
  BEGIN SELECT RAISE(ABORT, 'ledger entries are append-only'); END;
CREATE TABLE IF NOT EXISTS labels (
  owner INTEGER NOT NULL, other INTEGER NOT NULL, name TEXT NOT NULL, PRIMARY KEY (owner, other)
);
CREATE TABLE IF NOT EXISTS invites (
  digest TEXT PRIMARY KEY, creator INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, used_at TEXT, used_by INTEGER
);
CREATE INDEX IF NOT EXISTS invites_creator ON invites(creator);
CREATE TABLE IF NOT EXISTS reminders (
  pair TEXT NOT NULL, debt_seq INTEGER NOT NULL, key TEXT NOT NULL, user_id INTEGER NOT NULL,
  fire_at TEXT NOT NULL, sent_at TEXT, PRIMARY KEY (pair, debt_seq, key, user_id)
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(sent_at, fire_at);
"""


class Database:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn
        self.lock = asyncio.Lock()  # one writer at a time for read-check-append sequences

    @classmethod
    async def open(cls, path: str) -> Database:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.executescript(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()

    # ── users ──
    async def upsert_user(self, uid: int, name: str, lang: str, now: str) -> None:
        await self.conn.execute(
            "INSERT INTO users (id, name, lang, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (uid, name, lang, now),
        )
        await self.conn.commit()

    async def user(self, uid: int) -> dict | None:
        async with self.conn.execute("SELECT id, name, lang FROM users WHERE id = ?", (uid,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def set_lang(self, uid: int, lang: str) -> None:
        await self.conn.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, uid))
        await self.conn.commit()

    # ── ledger ──
    async def entries(self, pair: str) -> list[dict]:
        async with self.conn.execute("SELECT body FROM entries WHERE pair = ? ORDER BY seq", (pair,)) as cur:
            return [json.loads(row["body"]) async for row in cur]

    async def insert_entry(self, entry: dict) -> None:
        """Caller holds ``self.lock`` and has validated ``entry`` against the current chain."""
        a, b = (int(x) for x in entry["pair"].split(":"))
        await self.conn.execute("INSERT OR IGNORE INTO pairs (pair, a, b) VALUES (?, ?, ?)", (entry["pair"], a, b))
        await self.conn.execute(
            "INSERT INTO entries (pair, seq, body, hash, at) VALUES (?, ?, ?, ?, ?)",
            (entry["pair"], entry["seq"], canonical(entry), entry["hash"], entry["at"]),
        )
        await self.conn.commit()

    async def partners(self, me: int) -> list[int]:
        sql = "SELECT b AS other FROM pairs WHERE a = ? UNION SELECT a FROM pairs WHERE b = ?"
        async with self.conn.execute(sql, (me, me)) as cur:
            return sorted([row[0] async for row in cur])

    # ── names each user gives the other side ──
    async def set_label(self, owner: int, other: int, name: str) -> None:
        await self.conn.execute(
            "INSERT INTO labels (owner, other, name) VALUES (?, ?, ?) "
            "ON CONFLICT(owner, other) DO UPDATE SET name = excluded.name",
            (owner, other, name),
        )
        await self.conn.commit()

    async def labels(self, owner: int) -> dict[int, str]:
        sql = (
            "SELECT p.other, COALESCE(l.name, u.name, '#' || p.other) AS name FROM "
            "(SELECT b AS other FROM pairs WHERE a = ? UNION SELECT a FROM pairs WHERE b = ?) p "
            "LEFT JOIN labels l ON l.owner = ? AND l.other = p.other LEFT JOIN users u ON u.id = p.other"
        )
        async with self.conn.execute(sql, (owner, owner, owner)) as cur:
            return {row["other"]: row["name"] async for row in cur}

    # ── invites (only the sha256 of the token is stored) ──
    async def add_invite(self, digest: str, creator: int, payload: dict, now: str, expires: str) -> None:
        await self.conn.execute(
            "INSERT INTO invites (digest, creator, payload, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (digest, creator, canonical(payload), now, expires),
        )
        await self.conn.commit()

    async def take_invite(self, digest: str, user: int, now: str) -> dict | None:
        """Atomically mark an unused, unexpired invite as used. Returns it, or None (replay or expired)."""
        sql = (
            "UPDATE invites SET used_at = ?, used_by = ? WHERE digest = ? AND used_at IS NULL "
            "AND expires_at > ? AND creator != ? RETURNING creator, payload"
        )
        async with self.conn.execute(sql, (now, user, digest, now, user)) as cur:
            row = await cur.fetchone()
        await self.conn.commit()
        return {"creator": row["creator"], "payload": json.loads(row["payload"])} if row else None

    async def invite_creator(self, digest: str) -> int | None:
        async with self.conn.execute("SELECT creator FROM invites WHERE digest = ?", (digest,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    # ── reminders ──
    async def add_reminders(self, rows: list[tuple[str, int, str, int, str]]) -> None:
        await self.conn.executemany(
            "INSERT OR IGNORE INTO reminders (pair, debt_seq, key, user_id, fire_at) VALUES (?, ?, ?, ?, ?)", rows
        )
        await self.conn.commit()

    async def due_reminders(self, now: str, limit: int = 200) -> list[dict]:
        sql = (
            "SELECT pair, debt_seq, key, user_id, fire_at FROM reminders "
            "WHERE sent_at IS NULL AND fire_at <= ? ORDER BY fire_at LIMIT ?"
        )
        async with self.conn.execute(sql, (now, limit)) as cur:
            return [dict(row) async for row in cur]

    async def claim_reminder(self, r: dict, now: str) -> bool:
        """Mark as sent before sending, so a crash or a second worker can never send it twice."""
        cur = await self.conn.execute(
            "UPDATE reminders SET sent_at = ? WHERE pair = ? AND debt_seq = ? AND key = ? AND user_id = ? "
            "AND sent_at IS NULL",
            (now, r["pair"], r["debt_seq"], r["key"], r["user_id"]),
        )
        await self.conn.commit()
        return cur.rowcount == 1
