"""Tests for the persistent route registry."""

from __future__ import annotations

import pytest

from nttd.schemas.route import make_route_id
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


def _station_tile(stations: dict[int, Station], sid: int, map_width: int = 256) -> int:
    s = stations[sid]
    return s.y * map_width + s.x


def _make_vehicle(
    vid: int,
    company_id: int,
    station_ids: list[int],
    stations: dict[int, Station] | None = None,
    vtype: str = "train",
) -> Vehicle:
    dests = [
        _station_tile(stations, sid) if stations else sid
        for sid in station_ids
    ]
    orders = [
        Order(index=i, destination=dest, is_goto_station=True)
        for i, dest in enumerate(dests)
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
            1: _make_vehicle(1, 0, [10, 20], stations=stations),
            2: _make_vehicle(2, 0, [10, 20], stations=stations),
        }
        routes = registry.reconcile(vehicles, stations, game_date=100)
        assert len(routes) == 1
        route = routes[0]
        assert route.status == "unchecked"
        assert route.track_confirmed_at == 0
        assert route.vehicle_count == 2
        assert set(route.vehicle_ids) == {1, 2}
        assert route.station_ids == [10, 20]
        assert route.created_at == 100

    def test_stable_id_across_reconcile(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        v = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        routes1 = registry.reconcile(v, stations, game_date=100)
        routes2 = registry.reconcile(v, stations, game_date=200)
        assert routes1[0].route_id == routes2[0].route_id

    def test_multiple_routes(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {
            1: _make_vehicle(1, 0, [10, 20], stations=stations),
            2: _make_vehicle(2, 0, [20, 30], stations=stations),
        }
        routes = registry.reconcile(vehicles, stations, game_date=100)
        assert len(routes) == 2
        route_ids = {r.route_id for r in routes}
        assert len(route_ids) == 2

    def test_vehicle_removed_from_confirmed_route_leaves_track_built(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=100)

        routes = registry.reconcile({}, stations, game_date=200)
        assert len(routes) == 1
        assert routes[0].status == "track_built"
        assert routes[0].vehicle_count == 0

    def test_vehicle_removed_from_unconfirmed_route_removes_it(self, stations: dict[int, Station]) -> None:
        """Orders to two stations with no path between them leave nothing behind once
        the orders change. Keeping such a route would show a line that never existed."""
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, False, game_date=100)

        assert registry.reconcile({}, stations, game_date=200) == []

    def test_track_built_route_is_removed_when_a_station_goes(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=100)
        registry.reconcile({}, stations, game_date=200)

        remaining = {30: stations[30]}
        assert registry.reconcile({}, remaining, game_date=300) == []


    def test_a_removed_route_comes_back_when_vehicles_hold_its_orders_again(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, False, game_date=100)
        assert registry.reconcile({}, stations, game_date=200) == []

        routes = registry.reconcile(vehicles, stations, game_date=300)
        assert len(routes) == 1
        assert routes[0].route_id == route.route_id
        assert routes[0].status == "unchecked"
        assert routes[0].connection_checked_at == 0
        assert routes[0].created_at == 300


class TestRecordConnection:
    def test_path_found_makes_the_route_active(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]

        registry.record_connection(route.route_id, True, game_date=101)
        assert route.status == "active"
        assert route.track_confirmed_at == 101
        assert route.connection_checked_at == 101

    def test_no_path_marks_the_route_unconnected(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]

        registry.record_connection(route.route_id, False, game_date=101)
        assert route.status == "unconnected"
        assert route.track_confirmed_at == 0
        assert route.connection_checked_at == 101

        registry.reconcile(vehicles, stations, game_date=102)
        assert route.status == "unconnected"

    def test_a_path_built_later_turns_the_route_active(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, False, game_date=101)

        registry.record_connection(route.route_id, True, game_date=150)
        assert route.status == "active"
        assert route.track_confirmed_at == 150

    def test_confirmation_date_is_kept(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=101)

        registry.record_connection(route.route_id, True, game_date=200)
        assert route.track_confirmed_at == 101

    def test_unknown_route_is_ignored(self) -> None:
        registry = RouteRegistry()
        registry.record_connection("rt_missing", True, game_date=1)
        assert registry.get_routes() == []


class TestVehiclePaths:
    def test_a_vehicle_that_cannot_get_out_keeps_the_route_unconnected(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations), 2: _make_vehicle(2, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=100)

        registry.record_vehicle_paths(route.route_id, with_path=[1], without_path=[2], game_date=100)
        assert route.status == "unconnected"
        assert route.vehicles_without_path == [2]
        assert route.track_confirmed_at == 100

    def test_every_vehicle_with_a_path_makes_the_route_active(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=100)
        registry.record_vehicle_paths(route.route_id, with_path=[], without_path=[1], game_date=100)

        registry.record_vehicle_paths(route.route_id, with_path=[1], without_path=[], game_date=120)
        assert route.status == "active"
        assert route.vehicles_without_path == []

    def test_a_vehicle_that_passed_is_not_asked_again(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations), 2: _make_vehicle(2, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        assert registry.vehicles_to_check(route) == [1, 2]

        registry.record_vehicle_paths(route.route_id, with_path=[1], without_path=[2], game_date=100)
        assert registry.vehicles_to_check(route) == [2]

    def test_a_vehicle_without_answer_keeps_its_entry(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations), 2: _make_vehicle(2, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_vehicle_paths(route.route_id, with_path=[], without_path=[1, 2], game_date=100)

        registry.record_vehicle_paths(route.route_id, with_path=[], without_path=[2], game_date=101)
        assert route.vehicles_without_path == [1, 2]

    def test_a_vehicle_that_left_the_route_drops_out_of_the_list(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations), 2: _make_vehicle(2, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=100)
        registry.record_vehicle_paths(route.route_id, with_path=[1], without_path=[2], game_date=100)

        registry.reconcile({1: vehicles[1]}, stations, game_date=101)
        assert route.vehicles_without_path == []
        assert route.status == "active"

    def test_the_list_is_cleared_when_the_vehicles_leave(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        route = registry.reconcile(vehicles, stations, game_date=100)[0]
        registry.record_connection(route.route_id, True, game_date=100)
        registry.record_vehicle_paths(route.route_id, with_path=[], without_path=[1], game_date=100)

        registry.reconcile({}, stations, game_date=101)
        assert route.status == "track_built"
        assert route.vehicles_without_path == []
        assert registry.vehicles_to_check(route) == []

    def test_station_removed_marks_removed(self) -> None:
        registry = RouteRegistry()
        stations_full = {
            10: Station(id=10, x=50, y=60),
            20: Station(id=20, x=80, y=90),
        }
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations_full)}
        registry.reconcile(vehicles, stations_full, game_date=100)

        stations_partial: dict[int, Station] = {10: Station(id=10, x=50, y=60)}
        routes = registry.reconcile({}, stations_partial, game_date=200)
        assert len(routes) == 0

    def test_profit_aggregation(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        v1 = _make_vehicle(1, 0, [10, 20], stations=stations)
        v1.profit_this_year = 500
        v2 = _make_vehicle(2, 0, [10, 20], stations=stations)
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

    def test_connect_rail_stores_path_tiles(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        registry.register_planned_route(0, "train", [10, 20], game_date=50)

        path = [
            {"x": 50, "y": 60, "dir": 0},
            {"x": 55, "y": 65, "dir": 1},
            {"x": 60, "y": 70, "dir": 0},
            {"x": 65, "y": 75, "dir": 1},
            {"x": 80, "y": 90, "dir": 0},
        ]
        registry.on_action_result(
            "connect_rail",
            {"from_x": 50, "from_y": 60, "to_x": 80, "to_y": 90},
            {"path": path},
            stations,
            game_date=100,
        )
        route = registry.get_routes()[0]
        assert len(route.path_tiles) == 5
        assert route.path_tiles[0] == 60 * 256 + 50
        assert route.path_tiles[-1] == 90 * 256 + 80

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
        path = [{"x": 50, "y": 60, "dir": 0}, {"x": 80, "y": 90, "dir": 1}]
        registry.on_action_result(
            "connect_rail",
            {"from_x": 50, "from_y": 60, "to_x": 80, "to_y": 90},
            {"path": path},
            stations,
            game_date=100,
        )
        routes = registry.get_routes()
        assert len(routes) == 1
        assert routes[0].status == "track_built"
        assert len(routes[0].path_tiles) == 2

    def test_connect_rail_empty_path_still_works(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        registry.register_planned_route(0, "train", [10, 20], game_date=50)
        registry.on_action_result(
            "connect_rail",
            {"from_x": 50, "from_y": 60, "to_x": 80, "to_y": 90},
            {},
            stations,
            game_date=100,
        )
        route = registry.get_routes()[0]
        assert route.status == "track_built"
        assert route.path_tiles == []


class TestLookups:
    def test_route_for_vehicle(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {1: _make_vehicle(1, 0, [10, 20], stations=stations)}
        registry.reconcile(vehicles, stations, game_date=100)

        route = registry.route_for_vehicle(1)
        assert route is not None
        assert 1 in route.vehicle_ids

        assert registry.route_for_vehicle(999) is None

    def test_routes_for_station(self, stations: dict[int, Station]) -> None:
        registry = RouteRegistry()
        vehicles = {
            1: _make_vehicle(1, 0, [10, 20], stations=stations),
            2: _make_vehicle(2, 0, [20, 30], stations=stations),
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
            1: _make_vehicle(1, 0, [10, 20], stations=stations),
            2: _make_vehicle(2, 1, [20, 30], stations=stations),
        }
        registry.reconcile(vehicles, stations, game_date=100)

        assert len(registry.get_routes(company_id=0)) == 1
        assert len(registry.get_routes(company_id=1)) == 1
        assert len(registry.get_routes()) == 2
