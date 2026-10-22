"""The refresh asks the game whether each route can actually be run.

Vehicle orders may name two stations with no road or track between them, and a vehicle
may stand in a depot that no road joins. The game accepts both, so the orders alone
prove nothing. After each vehicle refresh the orchestrator walks the built road or rail
with trace_route, between consecutive stations and from each vehicle's own tile to the
first station, and records the answers on the route, which is what the agents read.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nttd.runtime.orchestrator import Orchestrator
from nttd.schemas.station import Station
from nttd.schemas.vehicle import Order, Vehicle
from nttd.state.world import WorldState


class _TracingClient:
    """An admin client that answers trace_route from a table of joined station pairs."""

    def __init__(self, joined: set[tuple[tuple[int, int], tuple[int, int]]], connected: bool = True) -> None:
        self.connected = connected
        self.joined = joined
        self.asked: list[dict[str, Any]] = []

    async def send_gamescript(self, action: str, params: dict | None = None, timeout: float = 10.0) -> dict[str, Any]:
        assert action == "trace_route"
        params = params or {}
        self.asked.append(params)
        pair = ((params["from_x"], params["from_y"]), (params["to_x"], params["to_y"]))
        exists = pair[0] == pair[1] or pair in self.joined or pair[::-1] in self.joined
        return {"success": True, "result": {"line_exists": exists, "transport_type": params["transport_type"]}}


def _world(vehicle_type: str, station_ids: list[int], positions: dict[int, tuple[int, int]] | None = None) -> WorldState:
    """One vehicle per entry of positions, default a single vehicle 7 standing on the first station."""
    world = WorldState()
    world.game.game_date = 500
    world.stations = {
        1: Station(id=1, name="A", company_id=0, x=10, y=10),
        2: Station(id=2, name="B", company_id=0, x=40, y=10),
        3: Station(id=3, name="C", company_id=0, x=40, y=80),
    }
    orders = [
        Order(index=i, destination=world.stations[sid].y * 256 + world.stations[sid].x, is_goto_station=True)
        for i, sid in enumerate(station_ids)
    ]
    first = world.stations[station_ids[0]]
    positions = positions or {7: (first.x, first.y)}
    world.vehicles = {
        vid: Vehicle(id=vid, type=vehicle_type, company_id=0, x=x, y=y, order_count=len(orders), orders=list(orders))
        for vid, (x, y) in positions.items()
    }
    return world


def _orchestrator(world: WorldState, client: _TracingClient) -> Orchestrator:
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.client = client  # type: ignore[assignment]
    orchestrator.world = world
    return orchestrator


def test_a_road_between_the_stations_makes_the_route_active() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient({((10, 10), (40, 10))})

    asyncio.run(_orchestrator(world, client).confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "active"
    assert route.track_confirmed_at == 500
    assert client.asked[0]["transport_type"] == "road"


def test_no_road_marks_the_route_unconnected() -> None:
    world = _world("road", [1, 3])
    client = _TracingClient(set())

    asyncio.run(_orchestrator(world, client).confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "unconnected"
    assert route.track_confirmed_at == 0
    assert route.connection_checked_at == 500


def test_every_consecutive_pair_must_be_joined() -> None:
    world = _world("train", [1, 2, 3])
    client = _TracingClient({((10, 10), (40, 10))})

    asyncio.run(_orchestrator(world, client).confirm_route_connections())

    assert world._derive_routes()[0].status == "unconnected"
    station_walks = [((p["from_x"], p["from_y"]), (p["to_x"], p["to_y"])) for p in client.asked[:2]]
    assert station_walks == [((10, 10), (40, 10)), ((40, 10), (40, 80))]
    assert {p["transport_type"] for p in client.asked} == {"rail"}


def test_a_confirmed_route_is_not_asked_again() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)

    asyncio.run(orchestrator.confirm_route_connections())
    asyncio.run(orchestrator.confirm_route_connections())

    # One walk between the stations, one from the vehicle to the first station.
    assert len(client.asked) == 2


DEPOT = (12, 12)


def test_a_truck_in_an_unjoined_depot_keeps_the_route_unconnected() -> None:
    world = _world("road", [1, 2], positions={7: DEPOT, 8: (10, 10)})
    client = _TracingClient({((10, 10), (40, 10))})

    asyncio.run(_orchestrator(world, client).confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "unconnected"
    assert route.track_confirmed_at == 500
    assert route.vehicles_without_path == [7]


def test_joining_the_depot_turns_the_route_active() -> None:
    world = _world("road", [1, 2], positions={7: DEPOT})
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)
    asyncio.run(orchestrator.confirm_route_connections())
    assert world._derive_routes()[0].status == "unconnected"

    client.joined.add((DEPOT, (10, 10)))
    asyncio.run(orchestrator.confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "active"
    assert route.vehicles_without_path == []


def test_a_vehicle_that_passed_is_not_walked_again_but_a_stuck_one_is() -> None:
    world = _world("road", [1, 2], positions={7: DEPOT, 8: (10, 10)})
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)

    asyncio.run(orchestrator.confirm_route_connections())
    before = len(client.asked)
    asyncio.run(orchestrator.confirm_route_connections())

    walks = client.asked[before:]
    assert [(w["from_x"], w["from_y"]) for w in walks] == [DEPOT]


def test_an_unconnected_route_is_asked_again_until_a_path_appears() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient(set())
    orchestrator = _orchestrator(world, client)

    asyncio.run(orchestrator.confirm_route_connections())
    client.joined.add(((10, 10), (40, 10)))
    world.game.game_date = 530
    asyncio.run(orchestrator.confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "active"
    assert route.track_confirmed_at == 530
    # Two station walks, one per refresh, and one vehicle walk that passed the first time.
    assert len(client.asked) == 3


def test_aircraft_need_no_track() -> None:
    world = _world("aircraft", [1, 3])
    client = _TracingClient(set())

    asyncio.run(_orchestrator(world, client).confirm_route_connections())

    assert world._derive_routes()[0].status == "active"
    assert client.asked == []


def test_a_game_that_cannot_answer_leaves_the_route_unchecked() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient(set(), connected=False)

    asyncio.run(_orchestrator(world, client).confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "unchecked"
    assert route.connection_checked_at == 0
