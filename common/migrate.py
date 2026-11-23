"""Простой раннер SQL-миграций: python -m common.migrate"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg

from common.config import DATABASE_URL

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
logger = logging.getLogger("migrate")


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def run_migrations(database_url: str = str(DATABASE_URL)) -> None:
    conn = await asyncpg.connect(_dsn(database_url))
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {
            r["filename"]
            for r in await conn.fetch("SELECT filename FROM schema_migrations")
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            logger.info("applying %s", path.name)
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)",
                    path.name,
                )
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_migrations())
