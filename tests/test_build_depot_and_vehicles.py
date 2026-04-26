"""Tests for build_depot_and_vehicles guards against duplicate trains."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.build_depot_and_vehicles import BuildDepotAndVehicles  # noqa: E402


class TestHasUnassignedVehicles:
    def test_detects_vehicle_with_zero_orders(self) -> None:
        obs = {"vehicles": [{"id": 5, "order_count": 2}, {"id": 18, "order_count": 0}]}
        assert BuildDepotAndVehicles._has_unassigned_vehicles(obs) is True

    def test_false_when_all_have_orders(self) -> None:
        obs = {"vehicles": [{"id": 5, "order_count": 2}, {"id": 9, "order_count": 2}]}
        assert BuildDepotAndVehicles._has_unassigned_vehicles(obs) is False

    def test_false_when_no_vehicles(self) -> None:
        obs = {"vehicles": []}
        assert BuildDepotAndVehicles._has_unassigned_vehicles(obs) is False


class TestHasEnoughVehicles:
    def test_blocks_when_vehicles_match_station_pairs(self) -> None:
        obs = {
            "stations": [{"id": 0}, {"id": 1}, {"id": 2}, {"id": 3}],
            "vehicles": [{"id": 5}, {"id": 18}],
        }
        assert BuildDepotAndVehicles._has_enough_vehicles(obs) is True

    def test_blocks_when_vehicles_exceed_station_pairs(self) -> None:
        obs = {
            "stations": [{"id": 0}, {"id": 1}],
            "vehicles": [{"id": 5}, {"id": 18}, {"id": 9}],
        }
        assert BuildDepotAndVehicles._has_enough_vehicles(obs) is True

    def test_allows_when_fewer_vehicles_than_pairs(self) -> None:
        obs = {
            "stations": [{"id": 0}, {"id": 1}, {"id": 2}, {"id": 3}],
            "vehicles": [{"id": 5}],
        }
        assert BuildDepotAndVehicles._has_enough_vehicles(obs) is False

    def test_allows_when_no_vehicles(self) -> None:
        obs = {
            "stations": [{"id": 0}, {"id": 1}],
            "vehicles": [],
        }
        assert BuildDepotAndVehicles._has_enough_vehicles(obs) is False


class TestRouteHasVehicle:
    @staticmethod
    def _tool() -> BuildDepotAndVehicles:
        return BuildDepotAndVehicles()

    def test_blocks_when_station_in_served_route(self) -> None:
        tool = self._tool()
        obs = {
            "stations": [{"id": 0, "tile": 100}, {"id": 1, "tile": 200}],
            "routes": [{"station_ids": [0, 1], "vehicle_count": 1}],
            "map_size": {"x": 256},
        }
        assert tool._route_has_vehicle(100, 200, obs, {"action_list": []}) is True

    def test_allows_when_no_served_routes(self) -> None:
        tool = self._tool()
        obs = {
            "stations": [{"id": 2, "tile": 300}, {"id": 3, "tile": 400}],
            "routes": [{"station_ids": [0, 1], "vehicle_count": 1}],
            "map_size": {"x": 256},
        }
        assert tool._route_has_vehicle(300, 400, obs, {"action_list": []}) is False

    def test_blocks_pending_build_train_nearby(self) -> None:
        tool = self._tool()
        obs = {
            "stations": [],
            "routes": [],
            "map_size": {"x": 256},
        }
        sly_data = {"action_list": [
            {"action_type": "build_train", "parameters": {"depot_tile": 105}},
        ]}
        assert tool._route_has_vehicle(100, None, obs, sly_data) is True
