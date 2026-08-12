"""Session-scoped observation routes: state queries, compact snapshots, GS queries."""

import logging
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
from nttd.state.route_planner import RoutePlanner
from nttd.state.situation import Situation

logger = logging.getLogger(__name__)

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


@router.get("/situation")
async def get_situation(session_id: str, company_id: int = 0) -> dict[str, Any]:
    """Where the company stands: money, what is built, what earns, and what is wrong.

    Arithmetic, not description. An agent that derives these from a raw observation
    spends a model call on counting and can get it wrong, which is a way for a good
    decision-maker to look bad at a benchmark meant to measure judgement.

    ``problems`` is the part worth reading first. Each entry says what is wrong, the
    detail, and why it matters, and every one is actionable: an unfinished route, a
    station nothing calls at, cargo piling up faster than it clears, a vehicle with no
    orders, a vehicle old enough that losing money means the route rather than settling.

    ``stations`` and ``vehicles`` carry tiles as well as counts, which is what makes this
    answerable: "what have I built and where". Without it a run can own two stations and
    have no way to find them, and one did, for 26 of its 28 steps.
    """
    runtime = deps.get_runtime(session_id)
    world = runtime.world
    return Situation(
        company=world.companies.get(company_id),
        stations=[s for s in world.stations.values() if s.company_id == company_id],
        vehicles=[v for v in world.vehicles.values() if v.company_id == company_id],
        routes=[r for r in world._derive_routes() if r.company_id == company_id],
        map_width=world.game.map_width,
    ).report()


@router.get("/path")
async def check_path(
    session_id: str,
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    transport_type: str = "rail",
    include_path: bool = False,
    max_iterations: int = 50_000,
    company_id: int = 0,
) -> dict[str, Any]:
    """Whether two points can be joined, before paying to find out.

    Every other build decision has a dry run behind it. The find_* family exists precisely
    so an agent need not guess whether a station fits, and it answers by dry running the
    real build inside the game. Connection was the one expensive, failure prone step with
    no equivalent, and it is the step that decides whether a route ever earns anything. One
    hand-played attempt cost 6729 for a line that then reported partial.

    The asymmetry was also unfair. nttd has known the answer all along: this pathfinder is
    the same one behind the operator-tier /pathfind route, kept on the operator side, so a
    contestant was being measured partly on guessing something the platform could tell it.

    Read only, and it changes nothing. It runs in Python over cached tiles, so it needs no
    game ticks and works while the world is paused between steps.

    Args:
        transport_type: rail, road or water.
        include_path: Return the tile by tile route as well. Off by default: a long path is
            hundreds of tiles, and the question here is usually whether to commit, not how.
            When on, the steps are in the shape build_path takes.

    What comes back deliberately does NOT include a money figure. The pathfinder's cost is
    its own search cost, in units of its terrain penalties, and reporting that as currency
    would be a number that looks authoritative and is not. Length, bridges and tunnels are
    what predict the bill; ask ``estimate_cost`` for money.
    """
    from nttd.pathfinding import service as pf_service  # noqa: PLC0415

    runtime = deps.get_runtime(session_id)
    width = runtime.world.game.map_width
    height = runtime.world.game.map_height
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=503, detail="Map dimensions not available yet")
    if pf_service.get_cache(session_id) is None:
        pf_service.init_cache(session_id, width, height)

    found = await pf_service.pathfind(
        session_id=session_id,
        from_x=from_x, from_y=from_y, to_x=to_x, to_y=to_y,
        transport_type=transport_type,
        gs_client=runtime.admin_client,
        company_id=company_id,
        max_iterations=max_iterations,
    )
    if found.get("error"):
        raise HTTPException(status_code=400, detail=str(found["error"]))

    path = found.get("path") or []
    answer: dict[str, Any] = {
        "connected": bool(found.get("found")),
        "transport_type": transport_type,
        "from": [from_x, from_y],
        "to": [to_x, to_y],
        "tiles": found.get("total_tiles", 0),
        "bridges": found.get("bridges", 0),
        "tunnels": found.get("tunnels", 0),
        # What the route would take to build, counted by kind of work.
        #
        # Without this the answer misleads. A water route across dry land reports connected,
        # because the planner is willing to dig canals the whole way, and an agent reads
        # that as "a ship can sail here". Saying build_canal 30 times is the difference
        # between a route and a civil engineering project.
        "work": _work(path),
        "searched_tiles": found.get("tiles_explored", 0),
        "search_ms": found.get("estimated_time_ms", 0),
    }
    if not answer["connected"]:
        # Why it gave up, in the two ways it can. Hitting the iteration ceiling is a
        # different problem from there being no route, and an agent that cannot tell them
        # apart abandons a corridor that only needed a longer search.
        answer["reason"] = (
            "the search hit its iteration limit, so raise max_iterations before "
            "concluding there is no route"
            if found.get("iterations", 0) >= max_iterations
            else "no route exists for this transport type between these points"
        )
    if include_path:
        answer["path"] = path
    return answer


def _work(path: list[dict[str, Any]]) -> dict[str, int]:
    """How many tiles of the route need each kind of construction.

    The planner marks every step with what it would take: move over what is already there,
    or build a canal, a bridge, a tunnel. Counting them turns "connected" into something an
    agent can weigh, since a line that is mostly existing track is a different proposition
    from one that is mostly digging.
    """
    counts: dict[str, int] = {}
    for step in path:
        action = str(step.get("action") or "move")
        if action in ("start", "end"):
            continue
        counts[action] = counts.get(action, 0) + 1
    return counts


@router.get("/routes")
async def get_route_candidates(
    session_id: str,
    agent_type: str = "general",
    compact: bool = False,
    company_id: int = 0,
) -> dict[str, Any]:
    """Which routes are worth building, ranked.

    Producer-to-consumer cargo pairs with distance and monthly production, town pairs
    scored by demand, which modes could serve each, and which you already serve.

    This existed and was unreachable. ``RoutePlanner.for_agent`` has a docstring saying
    it is for "the live agent observation pipeline", and its only importers were two
    offline report generators, so the one component built to tell an agent which routes
    pay was used exclusively to draw charts after the fact.

    Args:
        agent_type: Filter to what one mode can serve: road, rail, air, water, or
            general for everything.
        compact: Shorter field names and fewer items, for a smaller prompt.
        company_id: Whose existing routes count as already served.

    A route offered for water carries ``water_confirmed``. False means the water has not
    been checked rather than that it is absent: ask ``find_dock_spots``, which dry-runs
    the build inside the game.
    """
    runtime = deps.get_runtime(session_id)
    planner = RoutePlanner(
        industries=list(runtime.world.industries.values()),
        towns=list(runtime.world.towns.values()),
        stations=list(runtime.world.stations.values()),
        # The same source the snapshot uses. WorldState holds no route dictionary:
        # a route is reconciled from vehicle orders, so it is derived rather than stored.
        routes=runtime.world._derive_routes(),
    )
    offered = planner.for_agent(company_id, agent_type=agent_type, compact=compact)
    await _price_the_cargo_routes(runtime, offered)
    return offered


# Cargo route keys, long form and compact, so pricing works for both output shapes.
_CARGO_KEYS = ("top_unserved_cargo", "cargo")


async def _price_the_cargo_routes(runtime: Any, offered: dict[str, Any]) -> None:
    """Attach what each cargo route would pay, from the game's own figures.

    Ranking corridors without this can only compare production volume, which puts a short
    high volume low value run above a long lower volume high value one for no good reason.
    Measured at distance 32: steel pays 22 a unit, grain 18, livestock 16. No agent could
    see that before, because nothing in the read-only surface carried a payment rate.

    Priced here rather than in RoutePlanner because the figure comes from the GameScript
    and the planner is plain arithmetic over world state, with no way to ask. One query per
    distinct cargo and distance, so a page of candidates costs a handful of local calls.

    Silent on failure. A route list without prices is the list as it was before, which is
    worth serving; a 500 because the game was busy is not.
    """
    routes = [r for key in _CARGO_KEYS for r in (offered.get(key) or [])]
    if not routes:
        return
    try:
        labels = await _cargo_ids(runtime)
        priced: dict[tuple[int, int], int] = {}
        for route in routes:
            cargo_id = labels.get(str(route.get("cargo") or route.get("c") or ""))
            distance = route.get("distance") or route.get("d")
            if cargo_id is None or not isinstance(distance, int):
                continue
            key = (cargo_id, distance)
            if key not in priced:
                reply = await runtime.admin_client.send_gamescript(
                    "get_cargo_income",
                    {"cargo_id": cargo_id, "distance": distance},
                    timeout=10.0,
                )
                result = reply.get("result") or {}
                per_unit = result.get("income_per_unit")
                if not isinstance(per_unit, int):
                    continue
                priced[key] = per_unit
            per_unit = priced[key]
            monthly = route.get("monthly_production") or route.get("p") or 0
            route["income_per_unit"] = per_unit
            # What the corridor is worth if everything produced is carried. An upper bound,
            # and the number a build decision is actually weighed against.
            route["estimated_monthly_income"] = per_unit * int(monthly)
    except Exception:
        logger.debug("Could not price the route candidates", exc_info=True)


async def _cargo_ids(runtime: Any) -> dict[str, int]:
    """Cargo label to id, which is what the planner reports and the pricer needs."""
    reply = await runtime.admin_client.send_gamescript("get_cargo_types", {}, timeout=10.0)
    out: dict[str, int] = {}
    for entry in reply.get("result") or []:
        label = entry.get("label")
        cargo_id = entry.get("id")
        if isinstance(label, str) and isinstance(cargo_id, int):
            out[label] = cargo_id
    return out


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
