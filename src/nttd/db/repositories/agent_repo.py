"""Repository for agent connection and cycle queries."""

from typing import Any

from sqlalchemy import and_, select

from nttd.db.engine import get_session
from nttd.db.tables import agent_connections, agent_cycles


async def get_agent_connections(
    session_id: str,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """Query agent connections for a session."""
    async with get_session() as db:
        conditions = [agent_connections.c.session_id == session_id]
        if agent_id is not None:
            conditions.append(agent_connections.c.agent_id == agent_id)

        rows = (
            await db.execute(
                select(agent_connections)
                .where(and_(*conditions))
                .order_by(agent_connections.c.id.desc())
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_agent_cycles(
    session_id: str,
    connection_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query cycle records, optionally filtered by connection_id."""
    async with get_session() as db:
        conditions = [agent_cycles.c.session_id == session_id]
        if connection_id is not None:
            conditions.append(agent_cycles.c.connection_id == connection_id)

        rows = (
            await db.execute(
                select(agent_cycles)
                .where(and_(*conditions))
                .order_by(agent_cycles.c.cycle_number.desc())
                .limit(limit)
                .offset(offset)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_agent_summary(session_id: str) -> list[dict[str, Any]]:
    """Return per-agent aggregate stats for a session."""
    async with get_session() as db:
        rows = (
            await db.execute(
                select(
                    agent_connections.c.agent_id,
                    agent_connections.c.company_id,
                    agent_connections.c.framework,
                    agent_connections.c.model,
                    agent_connections.c.total_cycles,
                    agent_connections.c.total_actions,
                    agent_connections.c.successful_actions,
                    agent_connections.c.failed_actions,
                    agent_connections.c.avg_cycle_ms,
                    agent_connections.c.avg_decide_ms,
                    agent_connections.c.started_at,
                    agent_connections.c.stopped_at,
                ).where(agent_connections.c.session_id == session_id)
            )
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r._mapping)
            total = d.get("total_actions") or 0
            success = d.get("successful_actions") or 0
            d["success_rate"] = success / total if total > 0 else 0.0
            results.append(d)
        return results
