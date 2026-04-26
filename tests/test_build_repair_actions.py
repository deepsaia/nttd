"""Tests for build_repair_actions duplicate-train guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.build_repair_actions import BuildRepairActions  # noqa: E402


class TestDuplicateGuard:
    """Tests that build_repair_actions blocks duplicate train assignments."""

    @staticmethod
    def _tool() -> BuildRepairActions:
        return BuildRepairActions()

    def test_blocks_when_station_pair_has_vehicle(self) -> None:
        import asyncio
        tool = self._tool()
        obs = {
            "routes": [
                {"station_ids": [0, 1], "vehicle_count": 1, "profit_this_year": 0},
            ],
            "vehicles": [
                {"id": 8, "order_count": 2, "speed": 64},
                {"id": 20, "order_count": 0, "speed": 0},
            ],
        }
        sly_data = {"observation": obs, "action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke(
            {"vehicle_id": 20, "src_station_id": 0, "dst_station_id": 1},
            sly_data,
        )))
        assert result["success"] is False
        assert "BLOCKED" in result["error"]
        assert sly_data["action_list"] == []

    def test_blocks_when_one_station_overlaps(self) -> None:
        import asyncio
        tool = self._tool()
        obs = {
            "routes": [
                {"station_ids": [0, 1], "vehicle_count": 1},
            ],
            "vehicles": [
                {"id": 20, "order_count": 0},
            ],
        }
        sly_data = {"observation": obs, "action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke(
            {"vehicle_id": 20, "src_station_id": 0, "dst_station_id": 5},
            sly_data,
        )))
        assert result["success"] is False
        assert "BLOCKED" in result["error"]

    def test_allows_when_station_pair_has_no_vehicle(self) -> None:
        import asyncio
        tool = self._tool()
        obs = {
            "routes": [
                {"station_ids": [0, 1], "vehicle_count": 1},
            ],
            "vehicles": [
                {"id": 20, "order_count": 0},
            ],
        }
        sly_data = {"observation": obs, "action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke(
            {"vehicle_id": 20, "src_station_id": 2, "dst_station_id": 3},
            sly_data,
        )))
        assert result["success"] is True
        assert len(sly_data["action_list"]) == 3

    def test_blocks_vehicle_already_has_orders(self) -> None:
        import asyncio
        tool = self._tool()
        obs = {
            "routes": [],
            "vehicles": [
                {"id": 8, "order_count": 2, "speed": 64},
            ],
        }
        sly_data = {"observation": obs, "action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke(
            {"vehicle_id": 8, "src_station_id": 2, "dst_station_id": 3},
            sly_data,
        )))
        assert result["success"] is False
        assert "already has" in result["error"]

    def test_normal_assignment_queues_actions(self) -> None:
        import asyncio
        tool = self._tool()
        obs = {
            "routes": [],
            "vehicles": [
                {"id": 20, "order_count": 0},
            ],
        }
        sly_data = {"observation": obs, "action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke(
            {"vehicle_id": 20, "src_station_id": 2, "dst_station_id": 3},
            sly_data,
        )))
        assert result["success"] is True
        actions = sly_data["action_list"]
        assert len(actions) == 3
        assert actions[0]["action_type"] == "add_order"
        assert actions[0]["parameters"]["station_id"] == 2
        assert actions[1]["action_type"] == "add_order"
        assert actions[1]["parameters"]["station_id"] == 3
        assert actions[2]["action_type"] == "start_vehicle"

    def test_no_observation_allows_assignment(self) -> None:
        import asyncio
        tool = self._tool()
        sly_data = {"action_list": []}
        result = json.loads(asyncio.run(tool.async_invoke(
            {"vehicle_id": 20, "src_station_id": 0, "dst_station_id": 1},
            sly_data,
        )))
        assert result["success"] is True
        assert len(sly_data["action_list"]) == 3
