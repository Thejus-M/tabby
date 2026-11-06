"""Shared splits in SQLite, addressed by a short code, expiring after a TTL."""

import secrets
import time
from pathlib import Path

import aiosqlite

# No 0/O, 1/I/L: codes get read aloud and typed on phones.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS splits (
    code TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS splits_expires ON splits (expires_at);
"""


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


class ShareStore:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        await self.purge_expired()

    async def purge_expired(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM splits WHERE expires_at <= ?", (int(time.time()),))
            await db.commit()
            return cur.rowcount

    async def put(self, payload: str) -> str:
        now = int(time.time())
        async with aiosqlite.connect(self.path) as db:
            for _ in range(10):
                code = new_code()
                try:
                    await db.execute(
                        "INSERT INTO splits (code, payload, created_at, expires_at) VALUES (?, ?, ?, ?)",
                        (code, payload, now, now + self.ttl_seconds),
                    )
                except aiosqlite.IntegrityError:
                    continue
                await db.commit()
                return code
        raise RuntimeError("could not allocate a share code")

    async def get(self, code: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT payload FROM splits WHERE code = ? AND expires_at > ?",
                (code.strip().upper(), int(time.time())),
            )
            row = await cur.fetchone()
            return row[0] if row else None
