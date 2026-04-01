"""Repository for action history queries."""

from typing import Any

from sqlalchemy import and_, func, select

from nttd.db.engine import get_session
from nttd.db.tables import action_parameters, actions


async def get_actions(
    session_id: str,
    company_id: int | None = None,
    participant_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query action history with optional filters."""
    async with get_session() as db:
        conditions = [actions.c.session_id == session_id]
        if company_id is not None:
            conditions.append(actions.c.company_id == company_id)
        if participant_id is not None:
            conditions.append(actions.c.participant_id == participant_id)
        if action_type is not None:
            conditions.append(actions.c.action_type == action_type)
        if status is not None:
            conditions.append(actions.c.status == status)

        rows = (
            await db.execute(
                select(actions)
                .where(and_(*conditions))
                .order_by(actions.c.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_action_params(action_id: str) -> dict[str, str]:
    """Return parameters for a specific action."""
    async with get_session() as db:
        rows = (
            await db.execute(
                select(action_parameters).where(action_parameters.c.action_id == action_id)
            )
        ).fetchall()
        return {r.param_key: r.param_value for r in rows}


async def get_action_stats(session_id: str, company_id: int | None = None) -> dict[str, Any]:
    """Return aggregate action statistics for a session."""
    async with get_session() as db:
        conditions = [actions.c.session_id == session_id]
        if company_id is not None:
            conditions.append(actions.c.company_id == company_id)

        row = (
            await db.execute(
                select(
                    func.count().label("total"),
                    func.sum(func.iif(actions.c.status == "success", 1, 0)).label("success"),
                    func.sum(func.iif(actions.c.status == "failed", 1, 0)).label("failed"),
                ).where(and_(*conditions))
            )
        ).first()

        if row is None:
            return {"total": 0, "success": 0, "failed": 0, "success_rate": 0.0}

        total = row.total or 0
        success = row.success or 0
        failed = row.failed or 0
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": success / total if total > 0 else 0.0,
        }
