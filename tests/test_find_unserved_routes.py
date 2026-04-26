"""Tests for find_unserved_routes observation format handling and expansion gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.find_unserved_routes import FindUnservedRoutes  # noqa: E402


class TestNormalizeRoute:
    def test_compact_fields_mapped(self) -> None:
        route = {
            "src_id": 1, "dst_id": 2, "src": "Mine", "dst": "Station",
            "dist": 50, "prod": 100, "src_x": 10, "src_y": 20,
            "dst_x": 60, "dst_y": 70, "cargo": "COAL",
        }
        result = FindUnservedRoutes._normalize_route(route)
        assert result["source_id"] == 1
        assert result["dest_id"] == 2
        assert result["source_name"] == "Mine"
        assert result["dest_name"] == "Station"
        assert result["distance"] == 50
        assert result["monthly_production"] == 100
        assert result["source_x"] == 10
        assert result["dest_x"] == 60

    def test_full_fields_unchanged(self) -> None:
        route = {
            "source_id": 1, "dest_id": 2, "source_name": "Mine", "dest_name": "Station",
            "distance": 50, "monthly_production": 100,
            "source_x": 10, "source_y": 20, "dest_x": 60, "dest_y": 70,
            "cargo": "COAL",
        }
        result = FindUnservedRoutes._normalize_route(dict(route))
        assert result["source_id"] == 1
        assert result["dest_id"] == 2
        assert "src_id" not in result or result.get("source_id") == 1

    def test_full_fields_not_overwritten_by_compact(self) -> None:
        route = {
            "src_id": 99, "source_id": 1,
            "dst_id": 88, "dest_id": 2,
        }
        result = FindUnservedRoutes._normalize_route(route)
        assert result["source_id"] == 1
        assert result["dest_id"] == 2


class TestNormalizeTownRoute:
    def test_compact_town_fields_mapped(self) -> None:
        route = {
            "a_id": 10, "b_id": 20, "a": "Townsville", "b": "Cityburg",
            "dist": 80, "a_x": 5, "a_y": 15, "b_x": 85, "b_y": 95,
            "demand": 5000,
        }
        result = FindUnservedRoutes._normalize_town_route(route)
        assert result["town_a_id"] == 10
        assert result["town_b_id"] == 20
        assert result["town_a_name"] == "Townsville"
        assert result["town_b_name"] == "Cityburg"
        assert result["distance"] == 80
        assert result["town_a_x"] == 5
        assert result["town_b_x"] == 85

    def test_full_town_fields_not_overwritten(self) -> None:
        route = {"a_id": 99, "town_a_id": 10, "b_id": 88, "town_b_id": 20}
        result = FindUnservedRoutes._normalize_town_route(route)
        assert result["town_a_id"] == 10
        assert result["town_b_id"] == 20


class TestIntermediateProcessorFilter:
    """Tests that routes to intermediate processors are filtered out."""

    def test_filters_steel_mill(self) -> None:
        obs = {
            "industries": [
                {"id": 10, "name": "Iron Ore Mine",
                 "production": [{"cargo_label": "IORE"}], "accepted": []},
                {"id": 11, "name": "Steel Mill",
                 "production": [{"cargo_label": "STEL"}],
                 "accepted": [{"cargo_label": "IORE"}]},
            ],
        }
        routes = [
            {"source_id": 10, "dest_id": 11, "source_x": 50, "source_y": 50,
             "dest_x": 100, "dest_y": 100, "cargo": "IORE"},
        ]
        result = FindUnservedRoutes._filter_intermediate_destinations(routes, obs)
        assert len(result) == 0

    def test_allows_power_station(self) -> None:
        obs = {
            "industries": [
                {"id": 1, "name": "Coal Mine",
                 "production": [{"cargo_label": "COAL"}], "accepted": []},
                {"id": 2, "name": "Power Station",
                 "production": [], "accepted": [{"cargo_label": "COAL"}]},
            ],
        }
        routes = [
            {"source_id": 1, "dest_id": 2, "source_x": 50, "source_y": 50,
             "dest_x": 100, "dest_y": 100, "cargo": "COAL"},
        ]
        result = FindUnservedRoutes._filter_intermediate_destinations(routes, obs)
        assert len(result) == 1

    def test_allows_unknown_dest_industry(self) -> None:
        obs = {"industries": []}
        routes = [
            {"source_id": 1, "dest_id": 999, "source_x": 50, "source_y": 50,
             "dest_x": 100, "dest_y": 100, "cargo": "COAL"},
        ]
        result = FindUnservedRoutes._filter_intermediate_destinations(routes, obs)
        assert len(result) == 1

    def test_filters_sawmill_and_refinery(self) -> None:
        obs = {
            "industries": [
                {"id": 20, "name": "Forest",
                 "production": [{"cargo_label": "WOOD"}], "accepted": []},
                {"id": 21, "name": "Sawmill",
                 "production": [{"cargo_label": "GOOD"}],
                 "accepted": [{"cargo_label": "WOOD"}]},
                {"id": 30, "name": "Oil Wells",
                 "production": [{"cargo_label": "OIL_"}], "accepted": []},
                {"id": 31, "name": "Oil Refinery",
                 "production": [{"cargo_label": "GOOD"}],
                 "accepted": [{"cargo_label": "OIL_"}]},
            ],
        }
        routes = [
            {"source_id": 20, "dest_id": 21, "cargo": "WOOD",
             "source_x": 0, "source_y": 0, "dest_x": 50, "dest_y": 50},
            {"source_id": 30, "dest_id": 31, "cargo": "OIL_",
             "source_x": 0, "source_y": 0, "dest_x": 80, "dest_y": 80},
        ]
        result = FindUnservedRoutes._filter_intermediate_destinations(routes, obs)
        assert len(result) == 0


class TestExpansionGate:
    """Tests that expansion is blocked when active routes are unprofitable."""

    @staticmethod
    def _tool() -> FindUnservedRoutes:
        return FindUnservedRoutes()

    @staticmethod
    def _obs_with_routes(
        routes: list,
        vehicles: list | None = None,
        route_planning: dict | None = None,
    ) -> dict:
        return {
            "route_status": {"orphan_stations": 0},
            "vehicles": vehicles or [{"order_count": 2, "in_depot": False}],
            "routes": routes,
            "stations": [],
            "route_planning": route_planning or {
                "top_unserved_cargo": [
                    {
                        "source_id": 1, "dest_id": 2, "source_x": 200,
                        "source_y": 200, "dest_x": 220, "dest_y": 220,
                        "cargo": "COAL", "distance": 40,
                        "monthly_production": 100,
                    },
                ],
                "top_unserved_towns": [],
            },
        }

    def test_blocks_when_all_routes_unprofitable(self) -> None:
        import asyncio
        tool = self._tool()
        obs = self._obs_with_routes([
            {"vehicle_count": 1, "profit_this_year": -500, "profit_last_year": -200, "station_ids": [0, 1]},
            {"vehicle_count": 1, "profit_this_year": -300, "profit_last_year": -100, "station_ids": [2, 3]},
            {"vehicle_count": 1, "profit_this_year": -100, "profit_last_year": 0, "station_ids": [4, 5]},
        ])
        sly_data = {"observation": obs}
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        assert result["routes"] == []
        assert "none profitable" in result.get("reason", "")

    def test_allows_when_one_route_profitable(self) -> None:
        import asyncio
        tool = self._tool()
        obs = self._obs_with_routes([
            {"vehicle_count": 1, "profit_this_year": 500, "profit_last_year": 0, "station_ids": [0, 1]},
            {"vehicle_count": 1, "profit_this_year": -300, "profit_last_year": -100, "station_ids": [2, 3]},
            {"vehicle_count": 1, "profit_this_year": -100, "profit_last_year": 0, "station_ids": [4, 5]},
        ])
        sly_data = {"observation": obs}
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        assert len(result["routes"]) >= 1

    def test_allows_when_under_max_routes(self) -> None:
        import asyncio
        tool = self._tool()
        obs = self._obs_with_routes([
            {"vehicle_count": 1, "profit_this_year": -500, "profit_last_year": -200, "station_ids": [0, 1]},
        ])
        sly_data = {"observation": obs}
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        assert len(result["routes"]) >= 1


class TestPerCycleLimit:
    """Tests that only 1 new route per cycle is allowed."""

    def test_blocks_when_stations_already_queued(self) -> None:
        import asyncio
        tool = FindUnservedRoutes()
        obs = {
            "route_status": {"orphan_stations": 0},
            "vehicles": [{"order_count": 2, "in_depot": False}],
            "routes": [],
            "stations": [],
            "route_planning": {
                "top_unserved_cargo": [
                    {
                        "source_id": 1, "dest_id": 2, "source_x": 200,
                        "source_y": 200, "dest_x": 220, "dest_y": 220,
                        "cargo": "COAL",
                    },
                ],
                "top_unserved_towns": [],
            },
        }
        sly_data = {
            "observation": obs,
            "action_list": [
                {"action_type": "build_rail_station", "parameters": {"tile": 100}},
                {"action_type": "build_rail_station", "parameters": {"tile": 200}},
            ],
        }
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        assert result["routes"] == []
        assert "Already building" in result.get("reason", "")

    def test_allows_when_no_stations_queued(self) -> None:
        import asyncio
        tool = FindUnservedRoutes()
        obs = {
            "route_status": {"orphan_stations": 0},
            "vehicles": [{"order_count": 2, "in_depot": False}],
            "routes": [],
            "stations": [],
            "route_planning": {
                "top_unserved_cargo": [
                    {
                        "source_id": 1, "dest_id": 2, "source_x": 200,
                        "source_y": 200, "dest_x": 220, "dest_y": 220,
                        "cargo": "COAL",
                    },
                ],
                "top_unserved_towns": [],
            },
        }
        sly_data = {"observation": obs, "action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        assert len(result["routes"]) >= 1


class TestTownRoutes:
    """Tests that town/passenger routes are returned."""

    def test_town_routes_returned(self) -> None:
        import asyncio
        tool = FindUnservedRoutes()
        obs = {
            "route_status": {"orphan_stations": 0},
            "vehicles": [{"order_count": 2, "in_depot": False}],
            "routes": [],
            "stations": [],
            "route_planning": {
                "top_unserved_cargo": [],
                "top_unserved_towns": [
                    {
                        "town_a_id": 5, "town_a_name": "Townsville",
                        "town_a_x": 100, "town_a_y": 100,
                        "town_b_id": 8, "town_b_name": "Cityburg",
                        "town_b_x": 150, "town_b_y": 150,
                        "distance": 100, "demand_score": 5000,
                    },
                ],
            },
        }
        sly_data = {"observation": obs}
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        assert result["routes"] == []
        assert len(result["town_routes"]) == 1
        assert result["town_routes"][0]["town_a_id"] == 5

    def test_compact_town_routes_normalized(self) -> None:
        import asyncio
        tool = FindUnservedRoutes()
        obs = {
            "route_status": {"orphan_stations": 0},
            "vehicles": [{"order_count": 2, "in_depot": False}],
            "routes": [],
            "stations": [],
            "route_planning": {
                "top_unserved_cargo": [],
                "top_unserved_towns": [
                    {
                        "a_id": 5, "a": "Townsville", "a_x": 100, "a_y": 100,
                        "b_id": 8, "b": "Cityburg", "b_x": 150, "b_y": 150,
                        "dist": 100, "demand": 5000,
                    },
                ],
            },
        }
        sly_data = {"observation": obs}
        result = json.loads(asyncio.run(tool.async_invoke({}, sly_data)))
        town_route = result["town_routes"][0]
        assert town_route["town_a_id"] == 5
        assert town_route["town_b_id"] == 8
        assert town_route["town_a_name"] == "Townsville"
