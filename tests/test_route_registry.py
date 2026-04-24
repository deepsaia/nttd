"""Tests for the persistent route registry."""

from __future__ import annotations

import pytest

from nttd.schemas.route import Route, make_route_id
from nttd.schemas.station import Station
from nttd.schemas.vehicle import Order, Vehicle
from nttd.state.route_registry import RouteRegistry


@pytest.fixture()
def stations() -> dict[int, Station]:
    return {
        10: Station(id=10, name="Station A", company_id=0, x=50, y=60),
        20: Station(id=20, name="Station B", company_id=0, x=80, y=90),
        30: Station(id=30, name="Station C", company_id=0, x=120, y=140),
    }


def _make_vehicle(
    vid: int, company_id: int, station_ids: list[int], vtype: str = "train",
) -> Vehicle:
    orders = [
        Order(index=i, destination=sid, is_goto_station=True)
        for i, sid in enumerate(station_ids)
    ]
    return Vehicle(
        id=vid, type=vtype, company_id=company_id,
        order_count=len(orders), orders=orders,
    )


class TestMakeRouteId:
    def test_stable_across_calls(self) -> None:
        rid1 = make_route_id(0, "train", (10, 20))
        rid2 = make_route_id(0, "train", (10, 20))
        assert rid1 == rid2

    def test_sorted_stations_same_id(self) -> None:
        rid_ab = make_route_id(0, "train", (10, 20))
        rid_ba = make_route_id(0, "train", (20, 10))
        assert rid_ab == rid_ba

    def test_different_company_different_id(self) -> None:
        rid0 = make_route_id(0, "train", (10, 20))
        rid1 = make_route_id(1, "train", (10, 20))
        assert rid0 != rid1

    def test_different_type_different_id(self) -> None:
        rid_train = make_route_id(0, "train", (10, 20))
        rid_road = make_route_id(0, "road", (10, 20))
        assert rid_train != rid_road

    def test_prefix_format(self) -> None:
        rid = make_route_id(0, "train", (10, 20))
        assert rid.startswith("rt_")
        assert len(rid) == 11


class TestReconcile:
    def test_creates_route_from_vehicles(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {
            1: _make_vehicle(1, 0, [10, 20]),
            2: _make_vehicle(2, 0, [10, 20]),
        }
        routes = registry.reconcile(vehicles, stations, game_date=100)
        assert len(routes) == 1
        route = routes[0]
        assert route.status == "active"
        assert route.vehicle_count == 2
        assert set(route.vehicle_ids) == {1, 2}
        assert route.station_ids == [10, 20]
        assert route.created_at == 100

    def test_stable_id_across_reconcile(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        v = {1: _make_vehicle(1, 0, [10, 20])}
        routes1 = registry.reconcile(v, stations, game_date=100)
        routes2 = registry.reconcile(v, stations, game_date=200)
        assert routes1[0].route_id == routes2[0].route_id

    def test_multiple_routes(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {
            1: _make_vehicle(1, 0, [10, 20]),
            2: _make_vehicle(2, 0, [20, 30]),
        }
        routes = registry.reconcile(vehicles, stations, game_date=100)
        assert len(routes) == 2
        route_ids = {r.route_id for r in routes}
        assert len(route_ids) == 2

    def test_vehicle_removed_degrades_route(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20])}
        registry.reconcile(vehicles, stations, game_date=100)

        routes = registry.reconcile({}, stations, game_date=200)
        assert len(routes) == 1
        assert routes[0].status == "track_built"
        assert routes[0].vehicle_count == 0

    def test_station_removed_marks_removed(self) -> None:
        registry = RouteRegistry()
        stations_full = {
            10: Station(id=10, x=50, y=60),
            20: Station(id=20, x=80, y=90),
        }
        vehicles = {1: _make_vehicle(1, 0, [10, 20])}
        registry.reconcile(vehicles, stations_full, game_date=100)

        stations_partial: dict[int, Station] = {10: Station(id=10, x=50, y=60)}
        routes = registry.reconcile({}, stations_partial, game_date=200)
        assert len(routes) == 0

    def test_profit_aggregation(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        v1 = _make_vehicle(1, 0, [10, 20])
        v1.profit_this_year = 500
        v2 = _make_vehicle(2, 0, [10, 20])
        v2.profit_this_year = 300
        routes = registry.reconcile({1: v1, 2: v2}, stations, game_date=100)
        assert routes[0].total_profit_this_year == 800


class TestOnActionResult:
    def test_connect_rail_marks_track_built(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        registry.register_planned_route(0, "train", [10, 20], game_date=50)

        registry.on_action_result(
            "connect_rail",
            {"from_x": 50, "from_y": 60, "to_x": 80, "to_y": 90},
            {},
            stations,
            game_date=100,
        )
        routes = registry.get_routes()
        assert routes[0].status == "track_built"
        assert routes[0].track_confirmed_at == 100

    def test_depot_linked_to_route(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        registry.register_planned_route(0, "train", [10, 20], game_date=50)

        registry.on_action_result(
            "build_rail_depot",
            {"tile": 60 * 256 + 51},
            {},
            stations,
            game_date=100,
        )
        route = registry.get_routes()[0]
        assert route.depot_tile == 60 * 256 + 51

    def test_vehicle_linked_via_depot(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        route = registry.register_planned_route(0, "train", [10, 20], game_date=50)
        route.depot_tile = 15616

        registry.on_action_result(
            "build_train",
            {"depot_tile": 15616, "engine_id": 0},
            {"vehicle_id": 42},
            stations,
            game_date=100,
        )
        route = registry.get_routes()[0]
        assert 42 in route.vehicle_ids

    def test_connect_rail_creates_route_if_missing(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        registry.on_action_result(
            "connect_rail",
            {"from_x": 50, "from_y": 60, "to_x": 80, "to_y": 90},
            {},
            stations,
            game_date=100,
        )
        routes = registry.get_routes()
        assert len(routes) == 1
        assert routes[0].status == "track_built"


class TestLookups:
    def test_route_for_vehicle(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20])}
        registry.reconcile(vehicles, stations, game_date=100)

        route = registry.route_for_vehicle(1)
        assert route is not None
        assert 1 in route.vehicle_ids

        assert registry.route_for_vehicle(999) is None

    def test_routes_for_station(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {
            1: _make_vehicle(1, 0, [10, 20]),
            2: _make_vehicle(2, 0, [20, 30]),
        }
        registry.reconcile(vehicles, stations, game_date=100)

        routes_10 = registry.routes_for_station(10)
        assert len(routes_10) == 1

        routes_20 = registry.routes_for_station(20)
        assert len(routes_20) == 2

    def test_register_planned_route(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        route = registry.register_planned_route(0, "train", [10, 20], game_date=50)
        assert route.status == "planned"
        assert route.created_at == 50

        same = registry.register_planned_route(0, "train", [10, 20], game_date=60)
        assert same.route_id == route.route_id

    def test_get_routes_by_company(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {
            1: _make_vehicle(1, 0, [10, 20]),
            2: _make_vehicle(2, 1, [20, 30]),
        }
        registry.reconcile(vehicles, stations, game_date=100)

        assert len(registry.get_routes(company_id=0)) == 1
        assert len(registry.get_routes(company_id=1)) == 1
        assert len(registry.get_routes()) == 2
