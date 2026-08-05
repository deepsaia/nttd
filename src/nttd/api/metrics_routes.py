"""Metrics and replay API endpoints.

No leaderboard routes. A cross-run board is not nttd's job: nttd records a run
and packages it for submission, and whoever hosts a board ranks and displays the
rows. The two routes that used to live here ranked companies within one session,
which is a different thing wearing the same name.

Derived from the OpenTTD multiplayer/agent study, §12, §16 (local research notes, not in the repo).
"""

import logging
from typing import Any

from fastapi import APIRouter

from nttd.store import parquet_reader
from nttd.store.repositories import action_repo, entity_repo, event_repo, metrics_repo

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
    """Compare all companies at a specific game date (reads from Parquet)."""
    snap = parquet_reader.snapshot_at(session_id, game_date)
    if snap is None:
        return {"game_date": game_date, "companies": [], "count": 0}

    data = []
    for c in snap.get("companies", []):
        data.append({
            "company_id": c.get("id"),
            "balance": c.get("money", 0),
            "loan": c.get("loan", 0),
            "income": c.get("income", 0),
            "company_value": c.get("value", 0),
        })

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
# Replay
# ---------------------------------------------------------------------------

@router.get("/replay/sessions/{session_id}/snapshots")
async def get_replay_snapshots(session_id: str) -> dict[str, Any]:
    """Return snapshot metadata for timeline scrubbing (from Parquet)."""
    data = parquet_reader.read_rows(
        session_id, "snapshots", ["snapshot_id", "game_date", "tick", "captured_at"],
    )
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


# ---------------------------------------------------------------------------
# Agent data (session-scoped)
# ---------------------------------------------------------------------------

