"""Coded tool: build_depot_and_vehicles -- builds depot and buys engine + wagons.

Cycle N+1 work: after stations + track exist from the previous cycle,
finds a valid depot spot adjacent to existing track, then emits
build_rail_depot + buy_vehicle (engine) + buy_vehicle (wagons).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import query_gs

logger = logging.getLogger(__name__)


class BuildDepotAndVehicles(CodedTool):
    """Finds depot spot near track, builds depot, buys engine + wagons."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        station_tile: int = args["station_tile"]
        engine_id: int = args["engine_id"]
        wagon_id: Optional[int] = args.get("wagon_id")
        num_wagons: int = args.get("num_wagons", 3)

        depot_spot = await self._find_depot(station_tile, sly_data)
        if not depot_spot:
            return json.dumps({
                "success": False,
                "error": f"No depot spot found near tile {station_tile}. Track may not exist yet.",
            })

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])

        action_list.append({
            "action_type": "build_rail_depot",
            "parameters": {
                "tile": depot_spot["tile"],
                "direction": depot_spot.get("depot_direction", 0),
            },
        })
        action_list.append({
            "action_type": "buy_vehicle",
            "parameters": {
                "depot_tile": depot_spot["tile"],
                "engine_id": engine_id,
            },
        })

        wagon_count = 0
        if wagon_id is not None:
            for _ in range(num_wagons):
                action_list.append({
                    "action_type": "buy_vehicle",
                    "parameters": {
                        "depot_tile": depot_spot["tile"],
                        "engine_id": wagon_id,
                    },
                })
                wagon_count += 1

        sly_data["action_list"] = action_list

        return json.dumps({
            "success": True,
            "depot_tile": depot_spot["tile"],
            "actions_added": 2 + wagon_count,
            "note": "Orders + start will be added next cycle after vehicle appears in observation.",
        })

    async def _find_depot(
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
