"""Tests for read_route_health route health classification and context building."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.read_route_health import (  # noqa: E402
    _build_mappings,
    _classify_health,
    _find_unassigned_vehicles,
)


class TestBuildMappings:
    def test_maps_vehicles_to_routes(self) -> None:
        routes = [
            {"route_id": "rt_aaa", "station_ids": [0, 1], "vehicle_ids": [9, 18]},
            {"route_id": "rt_bbb", "station_ids": [2, 3], "vehicle_ids": [23]},
        ]
        v2r, r2s, r2v = _build_mappings(routes)
        assert v2r == {9: "rt_aaa", 18: "rt_aaa", 23: "rt_bbb"}
        assert r2s == {"rt_aaa": [0, 1], "rt_bbb": [2, 3]}
        assert r2v == {"rt_aaa": [9, 18], "rt_bbb": [23]}

    def test_empty_routes(self) -> None:
        v2r, r2s, r2v = _build_mappings([])
        assert v2r == {}
        assert r2s == {}
        assert r2v == {}


class TestClassifyHealth:
    def test_healthy_route_with_profit(self) -> None:
        routes = [{
            "route_id": "rt_a", "status": "active", "vehicle_count": 1,
            "first_vehicle_at": 100, "profit_this_year": 5000, "profit_last_year": 0,
        }]
        assert _classify_health(routes, 500) == {"rt_a": "healthy"}

    def test_new_route_under_threshold(self) -> None:
        routes = [{
            "route_id": "rt_a", "status": "active", "vehicle_count": 1,
            "first_vehicle_at": 400, "profit_this_year": 0, "profit_last_year": 0,
        }]
        assert _classify_health(routes, 500) == {"rt_a": "new"}

    def test_stalled_route_no_profit_over_threshold(self) -> None:
        routes = [{
            "route_id": "rt_a", "status": "active", "vehicle_count": 1,
            "first_vehicle_at": 100, "profit_this_year": 0, "profit_last_year": 0,
        }]
        assert _classify_health(routes, 500) == {"rt_a": "stalled"}

    def test_healthy_with_last_year_profit_only(self) -> None:
        routes = [{
            "route_id": "rt_a", "status": "active", "vehicle_count": 1,
            "first_vehicle_at": 100, "profit_this_year": 0, "profit_last_year": 3000,
        }]
        assert _classify_health(routes, 500) == {"rt_a": "healthy"}

    def test_incomplete_route_no_vehicles(self) -> None:
        routes = [{
            "route_id": "rt_a", "status": "active", "vehicle_count": 0,
        }]
        assert _classify_health(routes, 500) == {"rt_a": "incomplete"}

    def test_incomplete_route_track_built(self) -> None:
        routes = [{
            "route_id": "rt_a", "status": "track_built", "vehicle_count": 1,
        }]
        assert _classify_health(routes, 500) == {"rt_a": "incomplete"}

    def test_multiple_routes_mixed_health(self) -> None:
        routes = [
            {
                "route_id": "rt_a", "status": "active", "vehicle_count": 1,
                "first_vehicle_at": 100, "profit_this_year": 5000, "profit_last_year": 0,
            },
            {
                "route_id": "rt_b", "status": "active", "vehicle_count": 1,
                "first_vehicle_at": 100, "profit_this_year": 0, "profit_last_year": 0,
            },
            {
                "route_id": "rt_c", "status": "active", "vehicle_count": 1,
                "first_vehicle_at": 490, "profit_this_year": 0, "profit_last_year": 0,
            },
        ]
        health = _classify_health(routes, 500)
        assert health == {"rt_a": "healthy", "rt_b": "stalled", "rt_c": "new"}


class TestFindUnassignedVehicles:
    def test_finds_vehicle_with_zero_orders(self) -> None:
        vehicles = [
            {"id": 9, "order_count": 2},
            {"id": 18, "order_count": 0},
        ]
        v2r = {9: "rt_a", 18: "rt_a"}
        r2s = {"rt_a": [0, 1]}
        result = _find_unassigned_vehicles(vehicles, v2r, r2s)
        assert len(result) == 1
        assert result[0] == {"id": 18, "correct_route_id": "rt_a", "correct_stations": [0, 1]}

    def test_vehicle_not_in_any_route(self) -> None:
        vehicles = [{"id": 99, "order_count": 0}]
        result = _find_unassigned_vehicles(vehicles, {}, {})
        assert len(result) == 1
        assert result[0]["correct_route_id"] is None
        assert result[0]["correct_stations"] == []

    def test_all_vehicles_assigned(self) -> None:
        vehicles = [
            {"id": 9, "order_count": 2},
            {"id": 18, "order_count": 3},
        ]
        result = _find_unassigned_vehicles(vehicles, {9: "rt_a"}, {"rt_a": [0, 1]})
        assert result == []

    def test_vehicle_with_one_order_is_unassigned(self) -> None:
        vehicles = [{"id": 5, "order_count": 1}]
        v2r = {5: "rt_b"}
        r2s = {"rt_b": [2, 3]}
        result = _find_unassigned_vehicles(vehicles, v2r, r2s)
        assert len(result) == 1
        assert result[0]["correct_stations"] == [2, 3]
