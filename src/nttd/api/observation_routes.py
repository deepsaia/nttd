from typing import Any

from fastapi import APIRouter, HTTPException

from nttd.api.dependencies import action_tracker, admin_client, snapshot_broker_registry, world
from nttd.dashboard.metrics import MetricsWriter
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

_metrics = MetricsWriter()

router = APIRouter(prefix="/state", tags=["observation"])


@router.get("/full", response_model=StateSnapshot)
async def get_full_state() -> StateSnapshot:
    return world.snapshot()


@router.get("/company/{company_id}", response_model=Company)
async def get_company(company_id: int) -> Company:
    company = world.companies.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return company


@router.get("/towns", response_model=list[Town])
async def get_towns() -> list[Town]:
    return list(world.towns.values())


@router.get("/industries", response_model=list[Industry])
async def get_industries() -> list[Industry]:
    return list(world.industries.values())


@router.get("/stations", response_model=list[Station])
async def get_stations() -> list[Station]:
    return list(world.stations.values())


@router.get("/vehicles", response_model=list[Vehicle])
async def get_vehicles() -> list[Vehicle]:
    return list(world.vehicles.values())


@router.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """Latest per-company game metrics snapshot. Suitable for dashboards and monitoring."""
    return _metrics.get_latest()


@router.get("/compact", response_model=CompactSnapshot)
async def get_compact_state(company_id: int = -1) -> CompactSnapshot:
    """LLM-friendly summary of the current game state (~1-3 KB)."""
    game = world.game
    stations = list(world.stations.values())
    towns = list(world.towns.values())

    # Company section
    compact_company: CompactCompany | None = None
    if company_id >= 0 and company_id in world.companies:
        c = world.companies[company_id]
        # Build profit trend from broker history if an agent is scoped to this company
        profit_trend: list[int] = [c.income]
        for broker in snapshot_broker_registry.values():
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

    # Routes for this company — sorted by profit descending
    all_routes = world._derive_routes()
    company_routes = [r for r in all_routes if company_id < 0 or r.company_id == company_id]
    compact_routes = [
        CompactRoute(
            route_id=r.route_id,
            vehicle_type=r.vehicle_type,
            station_ids=r.station_ids,
            vehicle_count=r.vehicle_count,
            total_profit_this_year=r.total_profit_this_year,
        )
        for r in sorted(company_routes, key=lambda r: r.total_profit_this_year, reverse=True)
    ]

    # Subsidies (all, not filtered by company — they are opportunities for any company)
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
    recent_results = action_tracker.get_recent(5)
    recent_actions = []
    for result in reversed(recent_results):
        envelope = action_tracker.get_envelope(result.action_id)
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
async def gs_query(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Query game state via GameScript. Requires OpenTTD connection and nttd-gs loaded."""
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await admin_client.send_gamescript(action, params)
