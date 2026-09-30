"""
Migrate data from SQLite to PostgreSQL.

Usage (inside the backend container):
    python -m app.migrate_sqlite_to_pg

Or from host:
    podman compose exec backend python -m app.migrate_sqlite_to_pg

Requires:
    - SQLite DB at /app/data/conversations.db (source)
    - DATABASE_URL env var pointing to PostgreSQL (target)
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys

import asyncpg

from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SQLITE_PATH = "/app/data/conversations.db"

# Ordered by dependency (conversations before messages, etc.)
TABLES = [
    ("conversations", ["id", "title", "user_id", "created_at", "updated_at"]),
    ("messages", ["id", "conversation_id", "role", "content", "created_at"]),
    ("feedback", ["message_id", "conversation_id", "value", "created_at"]),
    ("page_index", ["page_id", "last_modified", "chunks_count", "indexed_at"]),
    ("query_analytics", ["id", "question", "sources_found", "answered", "created_at", "response_ms", "user_id", "space_keys", "sources"]),
    ("page_links", ["from_page_id", "to_page_id"]),
]


def _parse_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def migrate() -> None:
    settings = get_settings()
    if not settings.database_url:
        logger.error("DATABASE_URL not set — cannot migrate to PostgreSQL.")
        sys.exit(1)

    dsn = _parse_dsn(settings.database_url)

    # ── Read from SQLite ─────────────────────────────────────────────────
    logger.info("Reading from SQLite: %s", SQLITE_PATH)
    conn_sqlite = sqlite3.connect(SQLITE_PATH)
    conn_sqlite.row_factory = sqlite3.Row

    # ── Connect to PostgreSQL ────────────────────────────────────────────
    logger.info("Connecting to PostgreSQL: %s", dsn.split("@")[-1])  # log host only
    conn_pg = await asyncpg.connect(dsn)

    # ── Create schema ────────────────────────────────────────────────────
    from app.services.pg_conversation_store import _SCHEMA
    await conn_pg.execute(_SCHEMA)
    logger.info("PostgreSQL schema ensured.")

    # ── Migrate each table ───────────────────────────────────────────────
    total = 0
    for table_name, columns in TABLES:
        cursor = conn_sqlite.execute(f"SELECT * FROM {table_name}")  # noqa: S608 — trusted table names
        rows = cursor.fetchall()
        if not rows:
            logger.info("  %s: 0 rows (skip)", table_name)
            continue

        placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
        col_list = ", ".join(columns)
        on_conflict_col = columns[0]

        insert_sql = (
            f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({on_conflict_col}) DO NOTHING"
        )
        # page_links has composite PK
        if table_name == "page_links":
            insert_sql = (
                f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT (from_page_id, to_page_id) DO NOTHING"
            )

        batch = [tuple(row[col] for col in columns) for row in rows]
        await conn_pg.executemany(insert_sql, batch)
        logger.info("  %s: %d rows migrated", table_name, len(batch))
        total += len(batch)

    await conn_pg.close()
    conn_sqlite.close()
    logger.info("Migration complete: %d total rows transferred.", total)


if __name__ == "__main__":
    asyncio.run(migrate())
