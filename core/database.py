from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await self._create_tables(db)
            await db.commit()

    async def _create_tables(self, db: aiosqlite.Connection) -> None:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                staff_role_id INTEGER,
                admin_role_id INTEGER,
                tickets_category_id INTEGER,
                orders_channel_id INTEGER,
                proofs_channel_id INTEGER,
                logs_channel_id INTEGER,
                vouches_channel_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                product TEXT NOT NULL,
                price REAL NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proofs (
                proof_id TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                order_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                links_json TEXT,
                attachments_json TEXT,
                status TEXT NOT NULL,
                staff_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                stock_mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                key_value TEXT NOT NULL,
                is_used INTEGER NOT NULL DEFAULT 0,
                used_at TEXT,
                order_id TEXT,
                FOREIGN KEY(product_id) REFERENCES products(product_id)
            );

            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                claimed_by INTEGER,
                created_at TEXT NOT NULL,
                closed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS vouches (
                vouch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT NOT NULL,
                order_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        async with self._lock:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(query, params)
                await db.commit()

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(query, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows
