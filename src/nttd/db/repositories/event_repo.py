"""Repository for game event queries -- reads from Parquet."""

import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path("logs/sessions")


def set_sessions_dir(path: Path) -> None:
    global _SESSIONS_DIR
    _SESSIONS_DIR = path


async def get_events(
    session_id: str,
    event_type: str | None = None,
    company_id: int | None = None,
    from_date: int | None = None,
    to_date: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query game events with optional filters."""
    parquet_path = _SESSIONS_DIR / session_id / "events.parquet"
    if not parquet_path.exists():
        return []

    table = pq.read_table(parquet_path)
    rows = table.to_pylist()

    if event_type is not None:
        rows = [r for r in rows if r.get("event_type") == event_type]
    if company_id is not None:
        rows = [r for r in rows if r.get("company_id") == company_id]
    if from_date is not None:
        rows = [r for r in rows if r.get("game_date", 0) >= from_date]
    if to_date is not None:
        rows = [r for r in rows if r.get("game_date", 0) <= to_date]

    # Most recent first
    rows.reverse()
    return rows[offset:offset + limit]


async def get_messages(
    session_id: str,
    message_type: str | None = None,
    company_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Messages are no longer stored separately -- return empty list."""
    return []
