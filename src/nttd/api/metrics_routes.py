"""Metrics, leaderboard, and replay API endpoints.

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
# Leaderboard (derived from Parquet + agents.conf)
# ---------------------------------------------------------------------------

@router.get("/leaderboard/session/{session_id}")
async def get_session_leaderboard(session_id: str) -> dict[str, Any]:
    """Compute and return leaderboard from latest snapshot + agent data."""
    companies = await metrics_repo.get_company_latest(session_id)
    # No agent join: agents.conf was written by the deleted server-driven gameloop,
    # so it no longer exists. Contestant identity and spend live in result.parquet,
    # reported through POST /report.
    agent_by_company: dict[int, dict[str, Any]] = {}

    # Build leaderboard entries
    entries: list[dict[str, Any]] = []
    for c in companies:
        cid = c.get("id", c.get("company_id", 0))
        agent_info = agent_by_company.get(cid, {})
        action_stats = await action_repo.get_action_stats(session_id, company_id=cid)
        entries.append({
            "company_id": cid,
            "name": c.get("name", ""),
            "company_value": c.get("value", 0),
            "balance": c.get("money", 0),
            "income": c.get("income", 0),
            "agent_id": agent_info.get("agent_id"),
            "nttd_framework": agent_info.get("nttd_framework"),
            "total_actions": action_stats.get("total", 0),
            "success_rate": action_stats.get("success_rate", 0.0),
        })

    # Sort by company_value descending
    entries.sort(key=lambda e: e.get("company_value", 0), reverse=True)
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank

    return {"session_id": session_id, "leaderboard": entries}


@router.get("/leaderboard/compute/{session_id}")
async def compute_leaderboard(session_id: str) -> dict[str, Any]:
    """Row count for a session's leaderboard.

    A GET because it mutates nothing: the leaderboard is derived from Parquet on
    every request, so there is no stored ranking to recompute. It was a POST,
    which put a write-shaped route in the read-only public tier.
    """
    result = await get_session_leaderboard(session_id)
    return {"session_id": session_id, "ranked": len(result["leaderboard"])}


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

