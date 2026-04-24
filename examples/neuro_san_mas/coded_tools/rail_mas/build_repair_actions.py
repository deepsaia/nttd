"""Coded tool: build_repair_actions -- creates order + start actions for a vehicle."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

logger = logging.getLogger(__name__)


class BuildRepairActions(CodedTool):
    """Creates add_order x2 + start_vehicle actions and appends to sly_data."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        vid: int = args["vehicle_id"]
        src_sid: int = args["src_station_id"]
        dst_sid: int = args["dst_station_id"]

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])
        action_list.extend([
            {
                "action_type": "add_order",
                "parameters": {"vehicle_id": vid, "station_id": src_sid, "order_flags": 0},
            },
            {
                "action_type": "add_order",
                "parameters": {"vehicle_id": vid, "station_id": dst_sid, "order_flags": 0},
            },
            {
                "action_type": "start_vehicle",
                "parameters": {"vehicle_id": vid},
            },
        ])

        sly_data["action_list"] = action_list
        return f"Queued: add orders (stations {src_sid}, {dst_sid}) + start for vehicle {vid}"
