"""Coded tool: build_repair_actions -- creates order + start actions for a vehicle."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class BuildRepairActions(CodedTool):
    """Creates add_order x2 + start_vehicle actions and appends to sly_data."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        vid: int = args["vehicle_id"]
        src_sid: int = args["src_station_id"]
        dst_sid: int = args["dst_station_id"]

        obs = get_observation(sly_data)
        if obs:
            error = self._check_duplicate(vid, src_sid, dst_sid, obs)
            if error:
                return json.dumps({"success": False, "error": error})

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
        return json.dumps({
            "success": True,
            "message": f"Queued: add orders (stations {src_sid}, {dst_sid}) + start for vehicle {vid}",
        })

    @staticmethod
    def _check_duplicate(
        vid: int, src_sid: int, dst_sid: int, obs: Dict[str, Any],
    ) -> str:
        """Return error string if assignment would create a duplicate, else empty."""
        target_pair = {src_sid, dst_sid}
        for route in obs.get("routes", []):
            route_sids = set(route.get("station_ids", []))
            if route_sids & target_pair and route.get("vehicle_count", 0) >= 1:
                return (
                    f"BLOCKED: stations {src_sid},{dst_sid} already served by "
                    f"{route['vehicle_count']} vehicle(s). "
                    f"1 train per route (no signals)."
                )

        for v in obs.get("vehicles", []):
            if v.get("id") == vid and v.get("order_count", 0) >= 2:
                return (
                    f"BLOCKED: vehicle {vid} already has "
                    f"{v['order_count']} orders."
                )

        return ""
