"""Coded tool: check_vehicle_status -- reads vehicle and station status from observation."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class CheckVehicleStatus(CodedTool):
    """Returns vehicles needing repair (< 2 orders) and orphan station IDs."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"incomplete_vehicles": [], "orphan_station_ids": [],
                               "total_vehicles": 0, "running_vehicles": 0})

        vehicles: List[Dict[str, Any]] = obs.get("vehicles", [])
        route_status: Dict[str, Any] = obs.get("route_status", {})
        previous_actions: List[Dict[str, Any]] = obs.get("previous_actions", [])

        incomplete = [v for v in vehicles if v.get("order_count", 0) < 2]
        orphan_ids = route_status.get("orphan_station_ids", [])

        failed_actions = [
            {"action": p.get("action", ""), "error": p.get("error", ""),
             "parameters": p.get("parameters", {})}
            for p in previous_actions if p.get("status") == "failed"
        ]

        needs_depot_and_vehicle = bool(orphan_ids) and len(incomplete) == 0

        station_tiles: Dict[int, int] = {}
        if needs_depot_and_vehicle:
            for s in obs.get("stations", []):
                sid = s.get("id")
                if sid in orphan_ids:
                    station_tiles[sid] = s.get("tile", 0)

        sly_data["action_list"] = sly_data.get("action_list", [])

        return json.dumps({
            "incomplete_vehicles": [
                {"id": v.get("id"), "order_count": v.get("order_count", 0),
                 "speed": v.get("speed", 0), "in_depot": v.get("in_depot", False)}
                for v in incomplete
            ],
            "orphan_station_ids": orphan_ids,
            "orphan_station_tiles": station_tiles,
            "needs_depot_and_vehicle": needs_depot_and_vehicle,
            "total_vehicles": len(vehicles),
            "running_vehicles": len(vehicles) - len(incomplete),
            "failed_actions": failed_actions,
        })
