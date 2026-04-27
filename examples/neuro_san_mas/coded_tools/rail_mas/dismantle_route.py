"""Coded tool: dismantle_route -- sells vehicles on a stalled route."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class DismantleRoute(CodedTool):
    """Queues stop + send_to_depot + sell_vehicle for each vehicle on a route."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        route_id: str = args["route_id"]

        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"success": False, "error": "No observation available."})

        route = self._find_route(route_id, obs)
        if not route:
            return json.dumps({"success": False, "error": f"Route {route_id} not found."})

        vehicle_ids: List[int] = route.get("vehicle_ids", [])
        if not vehicle_ids:
            return json.dumps({
                "success": True,
                "route_id": route_id,
                "actions_added": 0,
                "note": "No vehicles on this route.",
            })

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])
        actions_before = len(action_list)

        for vid in vehicle_ids:
            action_list.append({
                "action_type": "stop_vehicle",
                "parameters": {"vehicle_id": vid},
            })
            action_list.append({
                "action_type": "send_to_depot",
                "parameters": {"vehicle_id": vid},
            })
            action_list.append({
                "action_type": "sell_vehicle",
                "parameters": {"vehicle_id": vid},
            })

        sly_data["action_list"] = action_list

        return json.dumps({
            "success": True,
            "route_id": route_id,
            "vehicle_ids": vehicle_ids,
            "actions_added": len(action_list) - actions_before,
            "note": "sell_vehicle may fail if vehicle not yet in depot; retried next cycle.",
        })

    @staticmethod
    def _find_route(route_id: str, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Find route dict from observation by route_id."""
        for r in obs.get("routes", []):
            if r.get("route_id") == route_id:
                return r
        return {}
