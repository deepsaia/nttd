"""Tests for check_vehicle_status matching logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.check_vehicle_status import CheckVehicleStatus  # noqa: E402


class TestServedStationIds:
    def test_returns_station_ids_from_routes_with_vehicles(self) -> None:
        obs = {
            "routes": [
                {"station_ids": [0, 1], "vehicle_count": 1},
                {"station_ids": [2, 3], "vehicle_count": 0},
            ],
        }
        assert CheckVehicleStatus._served_station_ids(obs) == {0, 1}

    def test_returns_empty_when_no_routes(self) -> None:
        obs = {"routes": []}
        assert CheckVehicleStatus._served_station_ids(obs) == set()

    def test_returns_empty_when_all_routes_have_zero_vehicles(self) -> None:
        obs = {
            "routes": [
                {"station_ids": [0, 1], "vehicle_count": 0},
            ],
        }
        assert CheckVehicleStatus._served_station_ids(obs) == set()

    def test_multiple_routes_with_vehicles(self) -> None:
        obs = {
            "routes": [
                {"station_ids": [0, 1], "vehicle_count": 2},
                {"station_ids": [4, 5], "vehicle_count": 1},
            ],
        }
        assert CheckVehicleStatus._served_station_ids(obs) == {0, 1, 4, 5}


class TestMatchVehiclesToOrphans:
    def test_matches_single_vehicle_to_closest_orphan_pair(self) -> None:
        incomplete = [{"id": 10, "x": 50, "y": 50}]
        orphan_ids = [2, 3]
        stations = [
            {"id": 2, "x": 40, "y": 45},
            {"id": 3, "x": 60, "y": 55},
        ]
        served: set[int] = set()

        result = CheckVehicleStatus._match_vehicles_to_orphans(
            incomplete, orphan_ids, stations, served,
        )
        assert len(result) == 1
        assert result[0]["vehicle_id"] == 10
        assert {result[0]["src_station_id"], result[0]["dst_station_id"]} == {2, 3}

    def test_skips_served_orphans(self) -> None:
        incomplete = [{"id": 10, "x": 50, "y": 50}]
        orphan_ids = [0, 1, 2, 3]
        stations = [
            {"id": 0, "x": 10, "y": 10},
            {"id": 1, "x": 20, "y": 10},
            {"id": 2, "x": 45, "y": 50},
            {"id": 3, "x": 55, "y": 50},
        ]
        served = {0, 1}

        result = CheckVehicleStatus._match_vehicles_to_orphans(
            incomplete, orphan_ids, stations, served,
        )
        assert len(result) == 1
        assert result[0]["vehicle_id"] == 10
        assert {result[0]["src_station_id"], result[0]["dst_station_id"]} == {2, 3}

    def test_returns_empty_when_fewer_than_two_orphans(self) -> None:
        incomplete = [{"id": 10, "x": 50, "y": 50}]
        orphan_ids = [2]
        stations = [{"id": 2, "x": 40, "y": 45}]

        result = CheckVehicleStatus._match_vehicles_to_orphans(
            incomplete, orphan_ids, stations, set(),
        )
        assert result == []

    def test_returns_empty_when_no_incomplete_vehicles(self) -> None:
        result = CheckVehicleStatus._match_vehicles_to_orphans(
            [], [2, 3], [{"id": 2, "x": 0, "y": 0}, {"id": 3, "x": 1, "y": 0}], set(),
        )
        assert result == []

    def test_multiple_vehicles_multiple_pairs(self) -> None:
        incomplete = [
            {"id": 10, "x": 10, "y": 10},
            {"id": 20, "x": 90, "y": 90},
        ]
        orphan_ids = [0, 1, 2, 3]
        stations = [
            {"id": 0, "x": 5, "y": 5},
            {"id": 1, "x": 15, "y": 15},
            {"id": 2, "x": 85, "y": 85},
            {"id": 3, "x": 95, "y": 95},
        ]

        result = CheckVehicleStatus._match_vehicles_to_orphans(
            incomplete, orphan_ids, stations, set(),
        )
        assert len(result) == 2
        ids_and_pairs = {
            (a["vehicle_id"], frozenset({a["src_station_id"], a["dst_station_id"]}))
            for a in result
        }
        assert (10, frozenset({0, 1})) in ids_and_pairs
        assert (20, frozenset({2, 3})) in ids_and_pairs

    def test_all_orphans_served_returns_empty(self) -> None:
        incomplete = [{"id": 10, "x": 50, "y": 50}]
        orphan_ids = [0, 1]
        stations = [
            {"id": 0, "x": 40, "y": 45},
            {"id": 1, "x": 60, "y": 55},
        ]
        served = {0, 1}

        result = CheckVehicleStatus._match_vehicles_to_orphans(
            incomplete, orphan_ids, stations, served,
        )
        assert result == []

    def test_more_vehicles_than_pairs(self) -> None:
        incomplete = [
            {"id": 10, "x": 10, "y": 10},
            {"id": 20, "x": 50, "y": 50},
            {"id": 30, "x": 90, "y": 90},
        ]
        orphan_ids = [0, 1]
        stations = [
            {"id": 0, "x": 45, "y": 45},
            {"id": 1, "x": 55, "y": 55},
        ]

        result = CheckVehicleStatus._match_vehicles_to_orphans(
            incomplete, orphan_ids, stations, set(),
        )
        assert len(result) == 1
        assert result[0]["vehicle_id"] == 20
