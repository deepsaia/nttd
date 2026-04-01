"""Repository for time-series metrics queries (dashboard charts)."""

from typing import Any

from sqlalchemy import and_, func, select

from nttd.db.engine import get_session
from nttd.db.tables import companies, finances, metrics


async def get_metric_series(
    session_id: str,
    metric_name: str,
    company_id: int | None = None,
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Return time-series data for a named metric."""
    async with get_session() as db:
        conditions = [
            metrics.c.session_id == session_id,
            metrics.c.metric_name == metric_name,
        ]
        if company_id is not None:
            conditions.append(metrics.c.company_id == company_id)
        if from_date is not None:
            conditions.append(metrics.c.game_date >= from_date)
        if to_date is not None:
            conditions.append(metrics.c.game_date <= to_date)

        rows = (
            await db.execute(
                select(metrics.c.game_date, metrics.c.company_id, metrics.c.metric_value)
                .where(and_(*conditions))
                .order_by(metrics.c.game_date)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_finance_series(
    session_id: str,
    company_id: int,
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Return financial time-series for a company."""
    async with get_session() as db:
        conditions = [
            finances.c.session_id == session_id,
            finances.c.company_id == company_id,
        ]
        if from_date is not None:
            conditions.append(finances.c.game_date >= from_date)
        if to_date is not None:
            conditions.append(finances.c.game_date <= to_date)

        rows = (
            await db.execute(
                select(finances)
                .where(and_(*conditions))
                .order_by(finances.c.game_date)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_company_latest(session_id: str) -> list[dict[str, Any]]:
    """Return latest snapshot for each company in a session."""
    async with get_session() as db:
        subq = (
            select(
                companies.c.company_id,
                func.max(companies.c.game_date).label("max_date"),
            )
            .where(companies.c.session_id == session_id)
            .group_by(companies.c.company_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(companies)
                .join(
                    subq,
                    and_(
                        companies.c.company_id == subq.c.company_id,
                        companies.c.game_date == subq.c.max_date,
                        companies.c.session_id == session_id,
                    ),
                )
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]


async def get_available_metrics(session_id: str) -> list[str]:
    """Return distinct metric names for a session."""
    async with get_session() as db:
        rows = (
            await db.execute(
                select(metrics.c.metric_name)
                .where(metrics.c.session_id == session_id)
                .distinct()
            )
        ).fetchall()
        return [r.metric_name for r in rows]
