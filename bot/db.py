"""Хранилище на SQLite. Одна таблица пользователей, отметки о выполнении и контакты."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id               INTEGER PRIMARY KEY,
    username            TEXT,
    full_name           TEXT,
    role                TEXT,               -- newbie | partner | leader
    status              TEXT DEFAULT 'new', -- new | active | trial_ended | graduate
    goal                TEXT,
    mentor_id           INTEGER,
    tz_offset           INTEGER,
    consent_at          TEXT,
    has_access          INTEGER DEFAULT 0,
    source              TEXT,
    current_day         INTEGER DEFAULT 0,
    day_done            INTEGER DEFAULT 0,
    program_started_on  TEXT,
    last_task_sent_on   TEXT,
    last_reminder_on    TEXT,
    last_active_on      TEXT,
    inactive_notified   INTEGER DEFAULT 0,
    graduated_on        TEXT,
    last_contacts_check_on TEXT,
    last_rating_sent_on TEXT,
    created_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_mentor ON users(mentor_id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS completions (
    user_id      INTEGER NOT NULL,
    day          INTEGER NOT NULL,
    local_date   TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    remind_on   TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_owner ON contacts(owner_id);
"""

USER_FIELDS = {
    "username", "full_name", "role", "status", "goal", "mentor_id", "tz_offset", "consent_at",
    "has_access", "source", "current_day", "day_done", "program_started_on", "last_task_sent_on",
    "last_reminder_on", "last_active_on", "inactive_notified", "graduated_on",
    "last_contacts_check_on", "last_rating_sent_on",
}
CONTACT_FIELDS = {"name", "status", "remind_on"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def _one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def _exec(self, sql: str, params: Iterable[Any] = ()) -> int:
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur.lastrowid

    # --- пользователи ---

    async def get_user(self, tg_id: int) -> dict | None:
        return await self._one("SELECT * FROM users WHERE tg_id = ?", (tg_id,))

    async def find_by_username(self, username: str) -> dict | None:
        username = username.lstrip("@").lower()
        return await self._one("SELECT * FROM users WHERE lower(username) = ?", (username,))

    async def create_user(self, tg_id: int, username: str | None, full_name: str,
                          tz_offset: int, source: str | None) -> dict:
        await self._exec(
            "INSERT OR IGNORE INTO users (tg_id, username, full_name, tz_offset, consent_at, source, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tg_id, username, full_name, tz_offset, utc_now_iso(), source, utc_now_iso()),
        )
        return await self.get_user(tg_id)

    async def update_user(self, tg_id: int, **fields: Any) -> None:
        unknown = set(fields) - USER_FIELDS
        if unknown:
            raise ValueError(f"Неизвестные поля: {unknown}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._exec(f"UPDATE users SET {sets} WHERE tg_id = ?", (*fields.values(), tg_id))

    async def all_users(self) -> list[dict]:
        return await self._all("SELECT * FROM users WHERE role IS NOT NULL")

    async def mentees(self, mentor_id: int) -> list[dict]:
        return await self._all("SELECT * FROM users WHERE mentor_id = ? ORDER BY created_at", (mentor_id,))

    async def count_active_mentees(self, mentor_id: int) -> int:
        row = await self._one(
            "SELECT COUNT(*) AS n FROM users WHERE mentor_id = ? AND role = 'newbie' AND status = 'active'",
            (mentor_id,),
        )
        return row["n"]

    async def downline(self, root_id: int, max_depth: int = 6) -> list[tuple[dict, int]]:
        """Вся структура под пользователем: [(user, глубина)], глубина 1 — личные."""
        result: list[tuple[dict, int]] = []
        seen = {root_id}
        level = [root_id]
        for depth in range(1, max_depth + 1):
            if not level:
                break
            marks = ",".join("?" * len(level))
            rows = await self._all(f"SELECT * FROM users WHERE mentor_id IN ({marks}) ORDER BY created_at", level)
            level = []
            for row in rows:
                if row["tg_id"] in seen:
                    continue
                seen.add(row["tg_id"])
                result.append((row, depth))
                level.append(row["tg_id"])
        return result

    async def delete_user(self, tg_id: int) -> None:
        await self.conn.execute("UPDATE users SET mentor_id = NULL WHERE mentor_id = ?", (tg_id,))
        await self.conn.execute("DELETE FROM completions WHERE user_id = ?", (tg_id,))
        await self.conn.execute("DELETE FROM contacts WHERE owner_id = ?", (tg_id,))
        await self.conn.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
        await self.conn.commit()

    # --- выполнение заданий ---

    async def add_completion(self, user_id: int, day: int, local_date: str) -> bool:
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO completions (user_id, day, local_date, completed_at) VALUES (?, ?, ?, ?)",
            (user_id, day, local_date, utc_now_iso()),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def completion_count(self, user_id: int) -> int:
        row = await self._one("SELECT COUNT(*) AS n FROM completions WHERE user_id = ?", (user_id,))
        return row["n"]

    async def completions_since(self, user_ids: list[int], since_local_date: str) -> dict[int, int]:
        if not user_ids:
            return {}
        marks = ",".join("?" * len(user_ids))
        rows = await self._all(
            f"SELECT user_id, COUNT(*) AS n FROM completions WHERE user_id IN ({marks}) AND local_date >= ?"
            " GROUP BY user_id",
            (*user_ids, since_local_date),
        )
        return {r["user_id"]: r["n"] for r in rows}

    async def all_completion_counts(self) -> dict[int, int]:
        rows = await self._all("SELECT user_id, COUNT(*) AS n FROM completions GROUP BY user_id")
        return {r["user_id"]: r["n"] for r in rows}

    # --- контакты ---

    async def add_contact(self, owner_id: int, name: str, status: str, remind_on: str | None) -> int:
        return await self._exec(
            "INSERT INTO contacts (owner_id, name, status, remind_on, created_at) VALUES (?, ?, ?, ?, ?)",
            (owner_id, name, status, remind_on, utc_now_iso()),
        )

    async def get_contact(self, owner_id: int, contact_id: int) -> dict | None:
        return await self._one("SELECT * FROM contacts WHERE id = ? AND owner_id = ?", (contact_id, owner_id))

    async def list_contacts(self, owner_id: int) -> list[dict]:
        return await self._all(
            "SELECT * FROM contacts WHERE owner_id = ? ORDER BY remind_on IS NULL, remind_on, name", (owner_id,)
        )

    async def update_contact(self, owner_id: int, contact_id: int, **fields: Any) -> None:
        unknown = set(fields) - CONTACT_FIELDS
        if unknown:
            raise ValueError(f"Неизвестные поля: {unknown}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        await self._exec(
            f"UPDATE contacts SET {sets} WHERE id = ? AND owner_id = ?", (*fields.values(), contact_id, owner_id)
        )

    async def delete_contact(self, owner_id: int, contact_id: int) -> None:
        await self._exec("DELETE FROM contacts WHERE id = ? AND owner_id = ?", (contact_id, owner_id))

    async def due_contacts(self, owner_id: int, local_date: str) -> list[dict]:
        return await self._all(
            "SELECT * FROM contacts WHERE owner_id = ? AND remind_on IS NOT NULL AND remind_on <= ? ORDER BY name",
            (owner_id, local_date),
        )

    async def contact_status_counts(self) -> dict[str, int]:
        rows = await self._all("SELECT status, COUNT(*) AS n FROM contacts GROUP BY status")
        return {r["status"]: r["n"] for r in rows}
