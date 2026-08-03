"""Session-scoped observation routes: state queries, compact snapshots, GS queries."""

from typing import Any

from fastapi import APIRouter, HTTPException

import nttd.api.dependencies as deps
from nttd.constants import READ_ONLY_GS_ACTIONS
from nttd.schemas.compact_snapshot import (
    CompactCompany,
    CompactRecentAction,
    CompactRoute,
    CompactSnapshot,
    CompactStation,
    CompactSubsidy,
    CompactTown,
    CompactVehicleCounts,
)
from nttd.schemas.company import Company
from nttd.schemas.industry import Industry
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.station import Station
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Vehicle

router = APIRouter(prefix="/sessions/{session_id}/state", tags=["observation"])


@router.get("/full", response_model=StateSnapshot)
async def get_full_state(session_id: str) -> StateSnapshot:
    runtime = deps.get_runtime(session_id)
    return runtime.world.snapshot()


@router.get("/company/{company_id}", response_model=Company)
async def get_company(session_id: str, company_id: int) -> Company:
    runtime = deps.get_runtime(session_id)
    company = runtime.world.companies.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return company


@router.get("/towns", response_model=list[Town])
async def get_towns(session_id: str) -> list[Town]:
    runtime = deps.get_runtime(session_id)
    return list(runtime.world.towns.values())


@router.get("/industries", response_model=list[Industry])
async def get_industries(session_id: str) -> list[Industry]:
    runtime = deps.get_runtime(session_id)
    return list(runtime.world.industries.values())


@router.get("/stations", response_model=list[Station])
async def get_stations(session_id: str) -> list[Station]:
    runtime = deps.get_runtime(session_id)
    return list(runtime.world.stations.values())


@router.get("/vehicles", response_model=list[Vehicle])
async def get_vehicles(session_id: str) -> list[Vehicle]:
    runtime = deps.get_runtime(session_id)
    return list(runtime.world.vehicles.values())


@router.get("/compact", response_model=CompactSnapshot)
async def get_compact_state(session_id: str, company_id: int = -1) -> CompactSnapshot:
    """LLM-friendly summary of the current game state (~1-3 KB)."""
    runtime = deps.get_runtime(session_id)
    world = runtime.world
    game = world.game
    stations = list(world.stations.values())
    towns = list(world.towns.values())

    # Company section
    compact_company: CompactCompany | None = None
    if company_id >= 0 and company_id in world.companies:
        c = world.companies[company_id]
        profit_trend: list[int] = [c.income]
        for broker in runtime.snapshot_broker_registry.values():
            history = broker.get_history(3)
            if history:
                trend = []
                for snap in reversed(history):
                    match = next((sc for sc in snap.companies if sc.id == company_id), None)
                    if match:
                        trend.append(match.income)
                if len(trend) > 1:
                    profit_trend = trend
                    break
        compact_company = CompactCompany(
            id=c.id,
            name=c.name,
            balance=c.money,
            loan=c.loan,
            income=c.income,
            profit_last_year=c.profit_last_year,
            company_value=c.value,
            profit_trend=profit_trend,
        )

    # Vehicle section
    company_vehicles = [v for v in world.vehicles.values() if company_id < 0 or v.company_id == company_id]
    by_type: dict[str, int] = {}
    in_depot = 0
    total_profit = 0
    for v in company_vehicles:
        by_type[v.type] = by_type.get(v.type, 0) + 1
        if v.in_depot:
            in_depot += 1
        total_profit += v.profit_this_year
    avg_profit = total_profit // len(company_vehicles) if company_vehicles else 0
    compact_vehicles = CompactVehicleCounts(
        total=len(company_vehicles),
        in_depot=in_depot,
        avg_profit_this_year=avg_profit,
        by_type=by_type,
    )

    # Top stations by cargo waiting
    company_stations = [s for s in stations if company_id < 0 or s.company_id == company_id]
    sorted_stations = sorted(
        company_stations,
        key=lambda s: sum(c.waiting for c in s.cargo_waiting),
        reverse=True,
    )
    top_stations = [
        CompactStation(
            id=s.id,
            name=s.name,
            cargo_total=sum(c.waiting for c in s.cargo_waiting),
        )
        for s in sorted_stations[:3]
    ]

    # Top towns by population
    sorted_towns = sorted(towns, key=lambda t: t.population, reverse=True)
    top_towns = [
        CompactTown(id=t.id, name=t.name, population=t.population)
        for t in sorted_towns[:3]
    ]

    # Routes for this company
    all_routes = world._derive_routes()
    company_routes = [r for r in all_routes if company_id < 0 or r.company_id == company_id]
    compact_routes = [
        CompactRoute(
            route_id=r.route_id,
            vehicle_type=r.vehicle_type,
            station_ids=r.station_ids,
            status=r.status,
            vehicle_count=r.vehicle_count,
            total_profit_this_year=r.total_profit_this_year,
        )
        for r in sorted(company_routes, key=lambda r: r.total_profit_this_year, reverse=True)
    ]

    # Subsidies
    compact_subsidies = [
        CompactSubsidy(
            id=s.id,
            cargo_label=s.cargo_label,
            src_name=s.src_name,
            dst_name=s.dst_name,
            value=s.value,
            remaining_years=s.remaining_years,
        )
        for s in sorted(world.subsidies, key=lambda s: s.value, reverse=True)
    ]

    # Recent actions
    recent_results = runtime.action_tracker.get_recent(5)
    recent_actions = []
    for result in reversed(recent_results):
        envelope = runtime.action_tracker.get_envelope(result.action_id)
        recent_actions.append(CompactRecentAction(
            action_id=result.action_id,
            action_type=envelope.action_type if envelope else "",
            status=result.status,
            company_id=envelope.company_id if envelope else 0,
        ))

    return CompactSnapshot(
        game_date=game.game_date,
        paused=game.paused,
        mode=game.mode,
        map_width=game.map_width,
        map_height=game.map_height,
        company=compact_company,
        vehicles=compact_vehicles,
        routes=compact_routes,
        subsidies=compact_subsidies,
        top_stations=top_stations,
        top_towns=top_towns,
        total_stations=len(company_stations),
        total_towns=len(towns),
        total_routes=len(company_routes),
        recent_actions=recent_actions,
    )


@router.post("/gs/query")
async def gs_query(session_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Query game state via GameScript.

    Read-only by contract, but the underlying transport is not: send_gamescript
    reaches every GameScript command, so this endpoint was a byte-for-byte clone of
    the guarded /actions/gs/execute. Verified: set_max_loan raised a scored
    company's credit ceiling from 300,000 to 9,000,000 through here while the
    guarded twin correctly returned 403.

    Mutating actions are therefore refused rather than merely discouraged.
    """
    runtime = deps.get_runtime(session_id)

    if action not in READ_ONLY_GS_ACTIONS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{action} is not a read-only query. This endpoint reaches the "
                f"GameScript directly, so it accepts observation commands only. "
                f"Use /actions/submit for gameplay."
            ),
        )

    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await runtime.admin_client.send_gamescript(action, params)
