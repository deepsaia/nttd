"""Repository for game event queries."""

from typing import Any

from sqlalchemy import select, and_

from nttd.db.engine import get_session
from nttd.db.tables import events, messages


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
    async with get_session() as db:
        conditions = [events.c.session_id == session_id]
        if event_type is not None:
            conditions.append(events.c.event_type == event_type)
        if company_id is not None:
            conditions.append(events.c.company_id == company_id)
        if from_date is not None:
            conditions.append(events.c.game_date >= from_date)
        if to_date is not None:
            conditions.append(events.c.game_date <= to_date)

        rows = (
            await db.execute(
                select(events)
                .where(and_(*conditions))
                .order_by(events.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_messages(
    session_id: str,
    message_type: str | None = None,
    company_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query messages with optional filters."""
    async with get_session() as db:
        conditions = [messages.c.session_id == session_id]
        if message_type is not None:
            conditions.append(messages.c.message_type == message_type)
        if company_id is not None:
            conditions.append(messages.c.company_id == company_id)

        rows = (
            await db.execute(
                select(messages)
                .where(and_(*conditions))
                .order_by(messages.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]
