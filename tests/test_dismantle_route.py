"""Tests for dismantle_route action queuing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.dismantle_route import DismantleRoute  # noqa: E402


def _make_sly(obs: dict) -> dict:
    return {"observation": json.dumps(obs), "action_list": []}


class TestDismantleRoute:
    @pytest.mark.asyncio
    async def test_queues_actions_for_route_vehicles(self) -> None:
        obs = {
            "routes": [
                {"route_id": "rt_abc", "vehicle_ids": [9, 18], "vehicle_count": 2},
            ],
            "vehicles": [
                {"id": 9, "in_depot": False},
                {"id": 18, "in_depot": False},
            ],
        }
        sly = _make_sly(obs)
        tool = DismantleRoute()
        result = json.loads(await tool.async_invoke({"route_id": "rt_abc"}, sly))

        assert result["success"] is True
        assert result["vehicle_ids"] == [9, 18]
        assert result["actions_added"] == 4

        actions = sly["action_list"]
        types = [a["action_type"] for a in actions]
        assert types == [
            "stop_vehicle", "send_to_depot",
            "stop_vehicle", "send_to_depot",
        ]
        assert actions[0]["parameters"]["vehicle_id"] == 9
        assert actions[2]["parameters"]["vehicle_id"] == 18

    @pytest.mark.asyncio
    async def test_sells_immediately_when_in_depot(self) -> None:
        obs = {
            "routes": [
                {"route_id": "rt_dep", "vehicle_ids": [7], "vehicle_count": 1},
            ],
            "vehicles": [
                {"id": 7, "in_depot": True},
            ],
        }
        sly = _make_sly(obs)
        tool = DismantleRoute()
        result = json.loads(await tool.async_invoke({"route_id": "rt_dep"}, sly))

        assert result["success"] is True
        assert result["actions_added"] == 1
        actions = sly["action_list"]
        assert actions[0]["action_type"] == "sell_vehicle"
        assert actions[0]["parameters"]["vehicle_id"] == 7

    @pytest.mark.asyncio
    async def test_route_not_found(self) -> None:
        obs = {"routes": []}
        sly = _make_sly(obs)
        tool = DismantleRoute()
        result = json.loads(await tool.async_invoke({"route_id": "rt_missing"}, sly))
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_route_with_no_vehicles(self) -> None:
        obs = {
            "routes": [
                {"route_id": "rt_empty", "vehicle_ids": [], "vehicle_count": 0},
            ],
        }
        sly = _make_sly(obs)
        tool = DismantleRoute()
        result = json.loads(await tool.async_invoke({"route_id": "rt_empty"}, sly))
        assert result["success"] is True
        assert result["actions_added"] == 0

    @pytest.mark.asyncio
    async def test_appends_to_existing_action_list(self) -> None:
        obs = {
            "routes": [
                {"route_id": "rt_x", "vehicle_ids": [5], "vehicle_count": 1},
            ],
            "vehicles": [
                {"id": 5, "in_depot": False},
            ],
        }
        sly = _make_sly(obs)
        sly["action_list"] = [{"action_type": "set_loan", "parameters": {"amount": 100000}}]
        tool = DismantleRoute()
        result = json.loads(await tool.async_invoke({"route_id": "rt_x"}, sly))
        assert result["actions_added"] == 2
        assert len(sly["action_list"]) == 3
        assert sly["action_list"][0]["action_type"] == "set_loan"
