"""Coded tool: find_unserved_routes -- returns unserved cargo routes from observation."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)

STATION_CATCHMENT = 10


class FindUnservedRoutes(CodedTool):
    """Returns unserved cargo routes not near existing stations."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"routes": [], "reason": "No observation available."})

        vehicles: List[Dict[str, Any]] = obs.get("vehicles", [])
        if vehicles and any(v.get("order_count", 0) < 2 for v in vehicles):
            return json.dumps({
                "routes": [],
                "reason": "Vehicles still need orders. Expansion deferred until all trains are running.",
            })

        route_planning: Dict[str, Any] = obs.get("route_planning", {})
        unserved: List[Dict[str, Any]] = route_planning.get("top_unserved_cargo", [])
        if not unserved:
            return json.dumps({"routes": [], "reason": "No unserved cargo routes available."})

        station_locs: List[Tuple[int, int]] = [
            (s.get("x", 0), s.get("y", 0)) for s in obs.get("stations", [])
        ]

        available: List[Dict[str, Any]] = []
        for route in unserved:
            src_x = route.get("source_x", 0)
            src_y = route.get("source_y", 0)
            dst_x = route.get("dest_x", 0)
            dst_y = route.get("dest_y", 0)
            near_existing = any(
                abs(sx - src_x) + abs(sy - src_y) <= STATION_CATCHMENT
                or abs(sx - dst_x) + abs(sy - dst_y) <= STATION_CATCHMENT
                for sx, sy in station_locs
            )
            if not near_existing:
                available.append(route)

        return json.dumps({"routes": available})
