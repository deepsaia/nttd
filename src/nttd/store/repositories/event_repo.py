"""Game event queries, over the shared Parquet read path."""

from __future__ import annotations

import logging
from typing import Any

from nttd.store import parquet_reader

logger = logging.getLogger(__name__)

_EVENTS = "events"


async def get_events(
    session_id: str,
    event_type: str | None = None,
    company_id: int | None = None,
    from_date: int | None = None,
    to_date: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query game events with optional filters, most recent first."""
    rows = parquet_reader.read_rows(session_id, _EVENTS)

    if event_type is not None:
        rows = [r for r in rows if r.get("event_type") == event_type]
    if company_id is not None:
        rows = [r for r in rows if r.get("company_id") == company_id]
    if from_date is not None:
        rows = [r for r in rows if r.get("game_date", 0) >= from_date]
    if to_date is not None:
        rows = [r for r in rows if r.get("game_date", 0) <= to_date]

    rows.reverse()
    return rows[offset:offset + limit]
