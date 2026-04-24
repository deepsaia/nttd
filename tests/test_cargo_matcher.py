"""Tests for the cargo-to-wagon matching utility."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.cargo_matcher import CargoMatcher  # noqa: E402

ENGINES = [
    {"id": 1, "name": "Steam Loco", "is_wagon": False, "power": 300, "price": 10000,
     "cargo_label": "", "cargo_type": 0, "capacity": 0, "rail_type": 0},
    {"id": 2, "name": "Diesel Loco", "is_wagon": False, "power": 600, "price": 20000,
     "cargo_label": "", "cargo_type": 0, "capacity": 0, "rail_type": 0},
    {"id": 10, "name": "Coal Truck", "is_wagon": True, "power": 0, "price": 500,
     "cargo_label": "COAL", "cargo_type": 1, "capacity": 20, "rail_type": 0},
    {"id": 11, "name": "Large Coal Hopper", "is_wagon": True, "power": 0, "price": 800,
     "cargo_label": "COAL", "cargo_type": 1, "capacity": 35, "rail_type": 0},
    {"id": 12, "name": "Passenger Car", "is_wagon": True, "power": 0, "price": 600,
     "cargo_label": "PASS", "cargo_type": 0, "capacity": 40, "rail_type": 0},
    {"id": 13, "name": "Iron Ore Wagon", "is_wagon": True, "power": 0, "price": 500,
     "cargo_label": "IORE", "cargo_type": 5, "capacity": 25, "rail_type": 0},
]

ENGINES_MIXED_RAIL = ENGINES + [
    {"id": 91, "name": "Maglev Coal Truck", "is_wagon": True, "power": 0, "price": 600,
     "cargo_label": "COAL", "cargo_type": 1, "capacity": 40, "rail_type": 3},
    {"id": 94, "name": "Maglev Goods Van", "is_wagon": True, "power": 0, "price": 700,
     "cargo_label": "GOOD", "cargo_type": 5, "capacity": 30, "rail_type": 3},
    {"id": 84, "name": "Maglev Loco", "is_wagon": False, "power": 2000, "price": 50000,
     "cargo_label": "", "cargo_type": 0, "capacity": 0, "rail_type": 3},
]


STATIONS = [
    {
        "id": 100, "name": "Coal Mine Halt", "x": 50, "y": 60,
        "cargo_acceptance": [
            {"cargo_label": "COAL", "accepts": False, "produces": True},
        ],
        "cargo_waiting": [
            {"cargo_label": "COAL", "waiting": 120},
        ],
    },
    {
        "id": 200, "name": "Power Plant Halt", "x": 80, "y": 90,
        "cargo_acceptance": [
            {"cargo_label": "COAL", "accepts": True, "produces": False},
        ],
        "cargo_waiting": [],
    },
    {
        "id": 300, "name": "Empty Station", "x": 120, "y": 140,
        "cargo_acceptance": [],
        "cargo_waiting": [],
    },
]


class TestSelectWagon:
    def test_exact_match_picks_highest_capacity(self) -> None:
        wagon = CargoMatcher.select_wagon("COAL", ENGINES)
        assert wagon is not None
        assert wagon["id"] == 11
        assert wagon["cargo_label"] == "COAL"
        assert wagon["capacity"] == 35

    def test_no_match_returns_none(self) -> None:
        wagon = CargoMatcher.select_wagon("GOLD", ENGINES)
        assert wagon is None

    def test_single_match(self) -> None:
        wagon = CargoMatcher.select_wagon("IORE", ENGINES)
        assert wagon is not None
        assert wagon["id"] == 13

    def test_passenger_match(self) -> None:
        wagon = CargoMatcher.select_wagon("PASS", ENGINES)
        assert wagon is not None
        assert wagon["id"] == 12

    def test_empty_engine_list(self) -> None:
        assert CargoMatcher.select_wagon("COAL", []) is None

    def test_no_wagons_in_list(self) -> None:
        locos_only = [e for e in ENGINES if not e.get("is_wagon")]
        assert CargoMatcher.select_wagon("COAL", locos_only) is None


class TestSelectEngine:
    def test_picks_cheapest_locomotive(self) -> None:
        engine = CargoMatcher.select_engine(ENGINES)
        assert engine is not None
        assert engine["id"] == 1
        assert engine["price"] == 10000

    def test_empty_list(self) -> None:
        assert CargoMatcher.select_engine([]) is None

    def test_wagons_only_returns_none(self) -> None:
        wagons_only = [e for e in ENGINES if e.get("is_wagon")]
        assert CargoMatcher.select_engine(wagons_only) is None


class TestGetStationCargo:
    def test_producing_station(self) -> None:
        cargo = CargoMatcher.get_station_cargo(100, STATIONS)
        assert cargo == "COAL"

    def test_accepting_station(self) -> None:
        cargo = CargoMatcher.get_station_cargo(200, STATIONS)
        assert cargo == "COAL"

    def test_empty_station(self) -> None:
        cargo = CargoMatcher.get_station_cargo(300, STATIONS)
        assert cargo is None

    def test_unknown_station(self) -> None:
        cargo = CargoMatcher.get_station_cargo(999, STATIONS)
        assert cargo is None


class TestGetPairCargo:
    def test_producer_to_consumer(self) -> None:
        cargo = CargoMatcher.get_pair_cargo(100, 200, STATIONS)
        assert cargo == "COAL"

    def test_consumer_to_producer(self) -> None:
        cargo = CargoMatcher.get_pair_cargo(200, 100, STATIONS)
        assert cargo == "COAL"

    def test_empty_stations(self) -> None:
        cargo = CargoMatcher.get_pair_cargo(300, 300, STATIONS)
        assert cargo is None


class TestCargoLabelToId:
    def test_known_cargo(self) -> None:
        cid = CargoMatcher.cargo_label_to_id("COAL", ENGINES)
        assert cid == 1

    def test_passenger(self) -> None:
        cid = CargoMatcher.cargo_label_to_id("PASS", ENGINES)
        assert cid == 0

    def test_unknown_cargo(self) -> None:
        cid = CargoMatcher.cargo_label_to_id("GOLD", ENGINES)
        assert cid is None


class TestRailTypeFiltering:
    def test_select_wagon_filters_by_rail_type(self) -> None:
        wagon = CargoMatcher.select_wagon("COAL", ENGINES_MIXED_RAIL, rail_type=0)
        assert wagon is not None
        assert wagon["id"] == 11
        assert wagon["rail_type"] == 0

    def test_select_wagon_maglev_has_higher_capacity(self) -> None:
        wagon = CargoMatcher.select_wagon("COAL", ENGINES_MIXED_RAIL)
        assert wagon is not None
        assert wagon["id"] == 91
        assert wagon["capacity"] == 40

    def test_select_wagon_no_rail_type_returns_any(self) -> None:
        wagon = CargoMatcher.select_wagon("COAL", ENGINES_MIXED_RAIL, rail_type=None)
        assert wagon is not None
        assert wagon["id"] == 91

    def test_select_wagon_maglev_only(self) -> None:
        wagon = CargoMatcher.select_wagon("COAL", ENGINES_MIXED_RAIL, rail_type=3)
        assert wagon is not None
        assert wagon["id"] == 91

    def test_select_engine_filters_by_rail_type(self) -> None:
        engine = CargoMatcher.select_engine(ENGINES_MIXED_RAIL, rail_type=0)
        assert engine is not None
        assert engine["id"] == 1

    def test_select_engine_maglev(self) -> None:
        engine = CargoMatcher.select_engine(ENGINES_MIXED_RAIL, rail_type=3)
        assert engine is not None
        assert engine["id"] == 84

    def test_select_engine_no_rail_type_picks_cheapest(self) -> None:
        engine = CargoMatcher.select_engine(ENGINES_MIXED_RAIL)
        assert engine is not None
        assert engine["id"] == 1
