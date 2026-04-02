"""Auto-apply database schema on startup.

Creates all tables defined in tables.py if they don't exist.
Includes column-level migrations for schema evolution.
"""

import logging

from sqlalchemy import text

from nttd.db.engine import get_engine
from nttd.db.tables import metadata

logger = logging.getLogger(__name__)


async def _add_column_if_missing(
    conn: object, table: str, column: str, col_type: str,
) -> None:
    """Add a column to an existing table if it doesn't already exist (SQLite)."""
    rows = await conn.execute(text(f"PRAGMA table_info({table})"))  # type: ignore[union-attr]
    existing = {r[1] for r in rows}
    if column not in existing:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))  # type: ignore[union-attr]
        logger.info("Added column %s.%s", table, column)


async def apply_migrations() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

        # Migration 1: add server process columns to sessions
        await _add_column_if_missing(conn, "sessions", "game_port", "INTEGER")
        await _add_column_if_missing(conn, "sessions", "admin_port", "INTEGER")
        await _add_column_if_missing(conn, "sessions", "pid", "INTEGER")

    logger.info("Database schema applied (%d tables).", len(metadata.tables))
