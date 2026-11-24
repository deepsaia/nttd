"""The refresh asks the game whether each route can actually be run.

Vehicle orders may name two stations with no road or track between them, and a vehicle
may stand in a depot that no road joins. The game accepts both, so the orders alone
prove nothing. After each vehicle refresh the orchestrator walks the built road or rail
with trace_route, between consecutive stations and from each vehicle's own tile to the
first station, and records the answers on the route, which is what the agents read.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from nttd.runtime.orchestrator import Orchestrator
from nttd.schemas.station import Station
from nttd.schemas.vehicle import Order, Vehicle
from nttd.state.route_registry import RouteRegistry
from nttd.state.world import WorldState


class _TracingClient:
    """An admin client that answers trace_route from a table of joined station pairs."""

    def __init__(
        self, joined: set[tuple[tuple[int, int], tuple[int, int]]], connected: bool = True,
        *, reply: dict[str, Any] | None = None, bidirectional: bool = True,
        delay: float = 0.0, invalidate: RouteRegistry | None = None,
    ) -> None:
        self.connected = connected
        self.joined = joined
        self.asked: list[dict[str, Any]] = []
        self.timeouts: list[float] = []
        self.reply = reply
        self.bidirectional = bidirectional
        self.delay = delay
        self.invalidate = invalidate

    async def send_gamescript(self, action: str, params: dict | None = None, timeout: float = 10.0) -> dict[str, Any]:
        assert action == "trace_route"
        params = params or {}
        self.asked.append(params)
        self.timeouts.append(timeout)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.invalidate is not None:
            self.invalidate.invalidate_connections()
            self.invalidate = None
        if self.reply is not None:
            return self.reply
        pair = ((params["from_x"], params["from_y"]), (params["to_x"], params["to_y"]))
        exists = pair[0] == pair[1] or pair in self.joined or (self.bidirectional and pair[::-1] in self.joined)
        return {"success": True, "result": {"line_exists": exists, "transport_type": params["transport_type"]}}


def _world(
    vehicle_type: str, station_ids: list[int], positions: dict[int, tuple[int, int]] | None = None
) -> WorldState:
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

    # Both directions of the repeating orders, plus the vehicle's station access.
    assert len(client.asked) == 3


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
    world.route_registry.invalidate_connections()
    asyncio.run(orchestrator.confirm_route_connections())

    route = world._derive_routes()[0]
    assert route.status == "active"
    assert route.vehicles_without_path == []


def test_a_vehicle_that_passed_is_cached_and_a_stuck_one_retries_after_backoff() -> None:
    world = _world("road", [1, 2], positions={7: DEPOT, 8: (10, 10)})
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)

    asyncio.run(orchestrator.confirm_route_connections())
    before = len(client.asked)
    asyncio.run(orchestrator.confirm_route_connections())
    assert len(client.asked) == before
    world.game.game_date += world.route_registry.RETRY_INITIAL_DAYS
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
    # Both station legs and vehicle access are refreshed after their evidence expires.
    assert len(client.asked) == 6


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


def test_connection_cache_expires_and_detects_removed_track():
    world = _world('road', [1, 2])
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)
    asyncio.run(orchestrator.confirm_route_connections())
    before = len(client.asked)
    client.joined.clear()
    world.game.game_date += world.route_registry.CONNECTION_CACHE_DAYS - 1
    asyncio.run(orchestrator.confirm_route_connections())
    assert len(client.asked) == before
    world.game.game_date += 1
    asyncio.run(orchestrator.confirm_route_connections())
    assert world._derive_routes()[0].status == 'unconnected'
    assert len(client.asked) > before


def test_infrastructure_mutation_invalidates_without_a_tile_recorder():
    from nttd.schemas.action_envelope import ActionEnvelope
    from nttd.schemas.action_result import ActionResult, ActionStatus
    world = _world('road', [1, 2])
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)
    orchestrator.tile_writer = None
    asyncio.run(orchestrator.confirm_route_connections())
    assert world._derive_routes()[0].status == 'active'
    asyncio.run(orchestrator.refresh_changed_tiles(
        ActionEnvelope(action_id='remove', company_id=0, action_type='demolish_tile',
                       parameters={'x': 20, 'y': 10}),
        ActionResult(action_id='remove', status=ActionStatus.SUCCESS),
    ))
    assert world._derive_routes()[0].status == 'unchecked'
    client.joined.clear()
    asyncio.run(orchestrator.confirm_route_connections())
    assert world._derive_routes()[0].status == 'unconnected'


def test_exhausted_search_leaves_connection_and_vehicle_path_unknown() -> None:
    world = _world('road', [1, 2])
    client = _TracingClient(set(), reply={'success': True, 'result': {'line_exists': False, 'exhausted': True}})
    asyncio.run(_orchestrator(world, client).confirm_route_connections())
    route = world._derive_routes()[0]
    assert route.status == 'unchecked'
    assert route.vehicles_without_path == []
    assert route.vehicles_with_unknown_path == [7]


def test_ship_connectivity_is_not_assumed():
    world = _world('ship', [1, 2])
    client = _TracingClient(set())
    asyncio.run(_orchestrator(world, client).confirm_route_connections())
    assert world._derive_routes()[0].status == 'unchecked'
    assert client.asked == []


def test_a_one_way_outward_path_does_not_prove_a_repeating_service() -> None:
    world = _world('road', [1, 2])
    client = _TracingClient({((10, 10), (40, 10))}, bidirectional=False)
    asyncio.run(_orchestrator(world, client).confirm_route_connections())
    assert world._derive_routes()[0].status == 'unconnected'


def test_explicit_null_connectivity_remains_unknown() -> None:
    from nttd.bridge.trace_route import line_exists
    client = _TracingClient(set(), reply={'success': True, 'result': {'line_exists': None}})
    assert asyncio.run(line_exists(client, 10, 10, 40, 10, 'road')) is None
    assert client.timeouts == [20.0]


def test_unmodeled_intermediate_orders_do_not_prove_a_station_only_route():
    for extra in [Order(destination=123, is_goto_waypoint=True),
                  Order(destination=123, is_goto_depot=True),
                  Order(is_conditional=True)]:
        world = _world('train', [1, 2])
        world.vehicles[7].orders.insert(1, extra)
        client = _TracingClient({((10, 10), (40, 10))})
        asyncio.run(_orchestrator(world, client).confirm_route_connections())
        assert world._derive_routes()[0].status == 'unchecked'


@pytest.mark.parametrize("answer", [False, None])
def test_failed_and_inconclusive_probes_back_off_on_the_game_clock(answer: bool | None) -> None:
    world = _world("road", [1, 2])
    client = _TracingClient(set(), reply={"success": True, "result": {"line_exists": answer}})
    orchestrator = _orchestrator(world, client)
    attempted_on: list[int] = []
    for date in range(500, 597):
        world.game.game_date = date
        before = len(client.asked)
        asyncio.run(orchestrator.confirm_route_connections())
        asyncio.run(orchestrator.confirm_route_connections())
        if len(client.asked) != before:
            attempted_on.append(date)
            assert len(client.asked) - before == 3
        route = world._derive_routes()[0]
        assert route.status == ("unconnected" if answer is False else "unchecked")
    assert attempted_on == [500, 505, 515, 535, 565, 595]


def test_large_itinerary_progresses_without_starving_another_route() -> None:
    world = _world("road", [1, 2])
    for sid in range(4, 10):
        world.stations[sid] = Station(id=sid, company_id=0, x=10 * sid, y=100)
    long_stops = [world.stations[sid] for sid in [1, 2, 3, 4, 5, 6, 7]]
    short_stops = [world.stations[sid] for sid in [8, 9]]
    joined: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for vid, stops in [(7, long_stops), (8, short_stops)]:
        orders = [Order(index=i, destination=s.y * 256 + s.x, is_goto_station=True)
                  for i, s in enumerate(stops)]
        world.vehicles[vid] = Vehicle(id=vid, company_id=0, type="road", x=stops[0].x, y=stops[0].y,
                                      order_count=len(orders), orders=orders)
        joined.update(((a.x, a.y), (b.x, b.y)) for a, b in zip(stops, stops[1:] + stops[:1]))
    client = _TracingClient(joined)
    orchestrator = _orchestrator(world, client)
    orchestrator.ROUTE_CHECKS_PER_REFRESH = 4

    for refresh in range(3):
        before = len(client.asked)
        asyncio.run(orchestrator.confirm_route_connections())
        assert 0 < len(client.asked) - before <= 4
        routes = {tuple(r.station_ids): r for r in world._derive_routes()}
        if refresh == 0:
            assert any(p["from_y"] == 10 for p in client.asked)
            assert any(p["from_x"] == 80 for p in client.asked)
        if refresh == 1:
            assert routes[8, 9].status == "active"
            assert routes[1, 2, 3, 4, 5, 6, 7].status == "unchecked"
    assert len(client.asked) == 11
    assert all(route.status == "active" for route in world._derive_routes())


def test_background_trace_count_has_a_finite_upper_bound() -> None:
    world = _world("road", [1, 2], positions={vid: (10, 10) for vid in range(40)})
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)

    asyncio.run(orchestrator.confirm_route_connections())

    assert len(client.asked) == 32
    route = world._derive_routes()[0]
    assert route.status == "unchecked"
    assert len(route.vehicles_with_unknown_path) == 10
    asyncio.run(orchestrator.confirm_route_connections())
    assert len(client.asked) == 42
    assert route.status == "active"


def test_seven_vehicle_route_stays_confirmable_at_fifteen_day_steps() -> None:
    world = _world("road", [1, 2], positions={vid: (10, 10) for vid in range(7)})
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)
    for date in range(500, 591, 15):
        world.game.game_date = date
        asyncio.run(orchestrator.confirm_route_connections())
        route = world._derive_routes()[0]
        assert route.status == "active"
        assert route.vehicles_with_unknown_path == []
    assert len(client.asked) == 36


def test_expiring_one_leg_preserves_newer_vehicle_and_station_evidence() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient({((10, 10), (40, 10))})
    orchestrator = _orchestrator(world, client)
    orchestrator.ROUTE_CHECKS_PER_REFRESH = 1
    for date in [500, 510, 520]:
        world.game.game_date = date
        asyncio.run(orchestrator.confirm_route_connections())
    assert world._derive_routes()[0].status == "active"

    world.game.game_date = 530
    asyncio.run(orchestrator.confirm_route_connections())

    assert len(client.asked) == 4
    assert client.asked[-1] == client.asked[0]
    assert world._derive_routes()[0].status == "active"


def test_one_slow_probe_cannot_consume_multiple_timeout_windows() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient(set(), delay=1.0)
    orchestrator = _orchestrator(world, client)
    orchestrator.ROUTE_CHECK_BUDGET_SECONDS = 0.01
    started = time.monotonic()

    asyncio.run(orchestrator.confirm_route_connections())

    assert time.monotonic() - started < 0.5
    assert len(client.asked) == 1
    assert 0 < client.timeouts[0] <= 0.01
    route = world._derive_routes()[0]
    assert route.status == "unchecked"
    assert route.vehicles_without_path == []
    assert route.vehicles_with_unknown_path == [7]


def test_an_in_flight_reply_cannot_restore_invalidated_evidence() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient({((10, 10), (40, 10))}, invalidate=world.route_registry)
    orchestrator = _orchestrator(world, client)

    asyncio.run(orchestrator.confirm_route_connections())

    assert len(client.asked) == 1
    assert world._derive_routes()[0].status == "unchecked"
    assert world.route_registry._connection_checks == {}
    asyncio.run(orchestrator.confirm_route_connections())
    assert len(client.asked) == 4
    assert world._derive_routes()[0].status == "active"


def test_changed_orders_bypass_retry_delay() -> None:
    world = _world("road", [1, 2])
    client = _TracingClient(set())
    orchestrator = _orchestrator(world, client)
    asyncio.run(orchestrator.confirm_route_connections())
    assert world._derive_routes()[0].status == "unconnected"

    world.vehicles[7].orders.reverse()
    client.joined.add(((10, 10), (40, 10)))
    asyncio.run(orchestrator.confirm_route_connections())

    assert len(client.asked) == 6
    assert world._derive_routes()[0].status == "active"
