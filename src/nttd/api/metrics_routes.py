"""Metrics, messages, leaderboard, and replay API endpoints.

Ref: docs/openttd_study_part4_multiplayer_agent_design.md §12, §16
"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from nttd.db.repositories import action_repo, entity_repo, event_repo, metrics_repo

logger = logging.getLogger(__name__)
router = APIRouter(tags=["metrics"])


# ---------------------------------------------------------------------------
# 2.3.22-2.3.25: Metrics / data
# ---------------------------------------------------------------------------

@router.get("/metrics/timeseries")
async def get_timeseries(
    session_id: str,
    metric_name: str,
    company_id: int | None = None,
    from_date: int | None = None,
    to_date: int | None = None,
) -> dict[str, Any]:
    data = await metrics_repo.get_metric_series(
        session_id, metric_name, company_id=company_id,
        from_date=from_date, to_date=to_date,
    )
    return {"metric_name": metric_name, "data": data, "count": len(data)}


@router.get("/metrics/latest")
async def get_latest_metrics(session_id: str) -> dict[str, Any]:
    companies = await metrics_repo.get_company_latest(session_id)
    return {"companies": companies, "count": len(companies)}


@router.get("/metrics/comparison")
async def get_comparison(session_id: str, game_date: int) -> dict[str, Any]:
    """Compare all companies at a specific game date."""
    from sqlalchemy import and_, select  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import finances  # noqa: PLC0415

    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(finances).where(
                    and_(
                        finances.c.session_id == session_id,
                        finances.c.game_date == game_date,
                    )
                )
            )
        ).fetchall()
        data = [dict(r._mapping) for r in rows]

    return {"game_date": game_date, "companies": data, "count": len(data)}


@router.get("/metrics/finances")
async def get_finance_series(
    session_id: str,
    company_id: int,
    from_date: int | None = None,
    to_date: int | None = None,
) -> dict[str, Any]:
    data = await metrics_repo.get_finance_series(
        session_id, company_id, from_date=from_date, to_date=to_date,
    )
    return {"company_id": company_id, "data": data, "count": len(data)}


@router.get("/metrics/available")
async def get_available_metrics(session_id: str) -> dict[str, Any]:
    names = await metrics_repo.get_available_metrics(session_id)
    return {"metrics": names}


@router.get("/metrics/agent/{participant_id}/performance")
async def get_agent_performance(participant_id: str, session_id: str) -> dict[str, Any]:
    stats = await action_repo.get_action_stats(session_id)
    # Get per-participant stats
    actions = await action_repo.get_actions(
        session_id, participant_id=participant_id, limit=0
    )
    total = len(actions)
    success = sum(1 for a in actions if a.get("status") == "success")
    return {
        "participant_id": participant_id,
        "total_actions": total,
        "success": success,
        "failed": total - success,
        "success_rate": success / total if total > 0 else 0.0,
        "session_stats": stats,
    }


# ---------------------------------------------------------------------------
# 2.3.26-2.3.28: Messages
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    session_id: str
    message_type: str = "chat"
    from_id: str | None = None
    to_id: str | None = None
    company_id: int | None = None
    body: str = ""


@router.post("/messages/send")
async def send_message(request: SendMessageRequest) -> dict[str, Any]:
    import uuid  # noqa: PLC0415

    from sqlalchemy import insert  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import messages  # noqa: PLC0415

    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    async with get_db_session() as db:
        await db.execute(
            insert(messages).values(
                session_id=request.session_id,
                message_id=msg_id,
                message_type=request.message_type,
                from_id=request.from_id,
                to_id=request.to_id,
                company_id=request.company_id,
                body=request.body,
            )
        )
        await db.commit()

    return {"message_id": msg_id, "status": "sent"}


@router.get("/messages/history")
async def get_message_history(
    session_id: str,
    message_type: str | None = None,
    company_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    msgs = await event_repo.get_messages(
        session_id, message_type=message_type, company_id=company_id,
        limit=limit, offset=offset,
    )
    return {"messages": msgs, "count": len(msgs)}


@router.get("/messages/inbox/{agent_id}")
async def get_inbox(agent_id: str, session_id: str, limit: int = 50) -> dict[str, Any]:
    from sqlalchemy import and_, or_, select  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import messages  # noqa: PLC0415

    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(messages)
                .where(
                    and_(
                        messages.c.session_id == session_id,
                        or_(
                            messages.c.to_id == agent_id,
                            messages.c.to_id == None,  # noqa: E711 — broadcast
                        ),
                    )
                )
                .order_by(messages.c.id.desc())
                .limit(limit)
            )
        ).fetchall()
        data = [dict(r._mapping) for r in rows]

    return {"agent_id": agent_id, "messages": data, "count": len(data)}


# ---------------------------------------------------------------------------
# 2.3.29-2.3.31: Leaderboard
# ---------------------------------------------------------------------------

@router.get("/leaderboard/session/{session_id}")
async def get_session_leaderboard(session_id: str) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import leaderboard  # noqa: PLC0415

    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(leaderboard)
                .where(leaderboard.c.session_id == session_id)
                .order_by(leaderboard.c.rank)
            )
        ).fetchall()
        data = [dict(r._mapping) for r in rows]

    return {"session_id": session_id, "leaderboard": data}


@router.get("/leaderboard/global")
async def get_global_leaderboard(limit: int = 50) -> dict[str, Any]:
    from sqlalchemy import func, select  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import leaderboard  # noqa: PLC0415

    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(
                    leaderboard.c.participant_id,
                    leaderboard.c.participant_type,
                    func.count().label("sessions"),
                    func.avg(leaderboard.c.rank).label("avg_rank"),
                    func.sum(leaderboard.c.total_cargo).label("total_cargo"),
                    func.avg(leaderboard.c.action_success_rate).label("avg_success_rate"),
                )
                .where(leaderboard.c.participant_id != None)  # noqa: E711
                .group_by(leaderboard.c.participant_id, leaderboard.c.participant_type)
                .order_by(func.avg(leaderboard.c.rank))
                .limit(limit)
            )
        ).fetchall()
        data = [dict(r._mapping) for r in rows]

    return {"leaderboard": data}


@router.post("/leaderboard/compute/{session_id}")
async def compute_leaderboard(session_id: str) -> dict[str, Any]:
    """Compute leaderboard rankings for a session based on latest company data."""
    from sqlalchemy import delete, insert  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import leaderboard  # noqa: PLC0415

    companies = await metrics_repo.get_company_latest(session_id)

    # Sort by company_value descending (from finances if available, fallback to 0)
    fin_data = {}
    for c in companies:
        cid = c["company_id"]
        fin_series = await metrics_repo.get_finance_series(session_id, cid)
        if fin_series:
            fin_data[cid] = fin_series[-1]

    ranked = sorted(companies, key=lambda c: fin_data.get(c["company_id"], {}).get("company_value", 0), reverse=True)

    async with get_db_session() as db:
        await db.execute(delete(leaderboard).where(leaderboard.c.session_id == session_id))
        for rank, company in enumerate(ranked, 1):
            cid = company["company_id"]
            fin = fin_data.get(cid, {})
            per_company_stats = await action_repo.get_action_stats(session_id, company_id=cid)
            await db.execute(
                insert(leaderboard).values(
                    session_id=session_id,
                    company_id=cid,
                    rank=rank,
                    final_balance=fin.get("balance", 0),
                    final_value=fin.get("company_value", 0),
                    final_rating=fin.get("performance_rating", 0),
                    total_cargo=fin.get("cargo_delivered", 0),
                    total_actions=per_company_stats.get("total", 0),
                    action_success_rate=per_company_stats.get("success_rate", 0.0),
                )
            )
        await db.commit()

    return {"session_id": session_id, "ranked": len(ranked)}


# ---------------------------------------------------------------------------
# 2.3.32-2.3.34: Replay
# ---------------------------------------------------------------------------

@router.get("/replay/sessions/{session_id}/snapshots")
async def get_replay_snapshots(session_id: str) -> dict[str, Any]:
    """Return snapshot metadata for timeline scrubbing."""
    from sqlalchemy import select  # noqa: PLC0415

    from nttd.db.engine import get_session as get_db_session  # noqa: PLC0415
    from nttd.db.tables import snapshots  # noqa: PLC0415

    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(
                    snapshots.c.snapshot_id,
                    snapshots.c.game_date,
                    snapshots.c.tick,
                    snapshots.c.captured_at,
                )
                .where(snapshots.c.session_id == session_id)
                .order_by(snapshots.c.game_date)
            )
        ).fetchall()
        data = [dict(r._mapping) for r in rows]

    return {"session_id": session_id, "snapshots": data, "count": len(data)}


@router.get("/replay/sessions/{session_id}/actions")
async def get_replay_actions(session_id: str) -> dict[str, Any]:
    actions = await action_repo.get_actions(session_id, limit=10000)
    return {"session_id": session_id, "actions": actions, "count": len(actions)}


@router.get("/replay/sessions/{session_id}/events")
async def get_replay_events(session_id: str) -> dict[str, Any]:
    events = await event_repo.get_events(session_id, limit=10000)
    return {"session_id": session_id, "events": events, "count": len(events)}


# ---------------------------------------------------------------------------
# Entity data (for dashboard)
# ---------------------------------------------------------------------------

@router.get("/data/towns")
async def get_towns(session_id: str) -> dict[str, Any]:
    data = await entity_repo.get_towns_latest(session_id)
    return {"towns": data, "count": len(data)}


@router.get("/data/industries")
async def get_industries(session_id: str) -> dict[str, Any]:
    data = await entity_repo.get_industries_latest(session_id)
    return {"industries": data, "count": len(data)}


@router.get("/data/stations")
async def get_stations(session_id: str, company_id: int | None = None) -> dict[str, Any]:
    data = await entity_repo.get_stations_latest(session_id, company_id=company_id)
    return {"stations": data, "count": len(data)}


@router.get("/data/vehicles")
async def get_vehicles(session_id: str, company_id: int | None = None) -> dict[str, Any]:
    data = await entity_repo.get_vehicles_latest(session_id, company_id=company_id)
    return {"vehicles": data, "count": len(data)}


@router.get("/data/subsidies")
async def get_subsidies(session_id: str) -> dict[str, Any]:
    data = await entity_repo.get_subsidies_latest(session_id)
    return {"subsidies": data, "count": len(data)}
