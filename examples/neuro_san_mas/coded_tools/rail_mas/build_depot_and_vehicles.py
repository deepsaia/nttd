"""Coded tool: build_depot_and_vehicles -- builds depot and buys engine + wagons.

Cycle N+1 work: after stations + track exist from the previous cycle,
finds a valid depot spot adjacent to existing track, then emits
build_rail_depot + build_train (engine + wagons assembled atomically).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import query_gs
from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class BuildDepotAndVehicles(CodedTool):
    """Finds depot spot near track, builds depot, buys engine + wagons."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        station_tile: int = args["station_tile"]
        engine_id: int = args["engine_id"]
        wagon_id: Optional[int] = args.get("wagon_id")
        num_wagons: int = args.get("num_wagons", 3)

        existing_depot = self._find_existing_depot(station_tile, sly_data)
        if existing_depot:
            depot_tile = existing_depot
            needs_build = False
        else:
            depot_spot = await self._find_new_depot_spot(station_tile, sly_data)
            if not depot_spot:
                return json.dumps({
                    "success": False,
                    "error": f"No depot spot found near tile {station_tile}. Track may not exist yet.",
                })
            depot_tile = depot_spot["tile"]
            needs_build = True

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])

        if needs_build:
            action_list.append({
                "action_type": "build_rail_depot",
                "parameters": {
                    "tile": depot_tile,
                    "direction": depot_spot.get("depot_direction", 0),
                },
            })

        params: Dict[str, Any] = {
            "depot_tile": depot_tile,
            "engine_id": engine_id,
        }
        if wagon_id is not None:
            params["wagon_id"] = wagon_id
            params["num_wagons"] = num_wagons

        action_list.append({
            "action_type": "build_train",
            "parameters": params,
        })

        sly_data["action_list"] = action_list

        actions_added = 2 if needs_build else 1
        return json.dumps({
            "success": True,
            "depot_tile": depot_tile,
            "reused_depot": not needs_build,
            "actions_added": actions_added,
            "note": "Orders + start will be added next cycle after vehicle appears in observation.",
        })

    def _find_existing_depot(
        self, near_tile: int, sly_data: Dict[str, Any],
    ) -> Optional[int]:
        """Return depot tile if a vehicle is in a depot near station_tile."""
        obs = get_observation(sly_data)
        if not obs:
            return None
        map_width = obs.get("map_size", {}).get("x", 256)
        near_x = near_tile % map_width
        near_y = near_tile // map_width
        for v in obs.get("vehicles", []):
            if v.get("in_depot", False):
                vx = v.get("x", 0)
                vy = v.get("y", 0)
                if abs(vx - near_x) + abs(vy - near_y) <= 15:
                    return vy * map_width + vx
        return None

    async def _find_new_depot_spot(
        self, near_tile: int, sly_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find a depot spot near existing track."""
        for radius in (10, 15):
            try:
                result = await query_gs(
                    "find_rail_depot_spot",
                    {"tile": near_tile, "radius": radius, "max_results": 3},
                    sly_data,
                )
                spots = result.get("result", [])
                if spots:
                    return spots[0]
            except Exception:
                logger.warning(
                    "find_rail_depot_spot failed near tile %d radius %d",
                    near_tile, radius, exc_info=True,
                )
        return None
