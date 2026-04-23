"""Coded tool: build_route_actions -- validates spots and assembles route build actions.

Takes LLM selections (route, engine, wagon), validates station/depot spots
via HTTP, and writes the full action sequence to sly_data["action_list"].
Includes wagon purchases for cargo capacity.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool

logger = logging.getLogger(__name__)


class BuildRouteActions(CodedTool):
    """Validates spots and builds the complete action sequence for a new route."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        src_industry_id: int = args["source_industry_id"]
        dst_industry_id: int = args["dest_industry_id"]
        engine_id: int = args["engine_id"]
        wagon_id: Optional[int] = args.get("wagon_id")
        num_wagons: int = args.get("num_wagons", 3)

        src_spot = await self._find_station(src_industry_id, sly_data)
        if not src_spot:
            return json.dumps({"success": False, "error": f"No station spot for source industry {src_industry_id}"})

        dst_spot = await self._find_station(dst_industry_id, sly_data)
        if not dst_spot:
            return json.dumps({"success": False, "error": f"No station spot for dest industry {dst_industry_id}"})

        depot_spot = await self._find_depot(src_spot["tile"], sly_data)
        if not depot_spot:
            depot_spot = await self._find_depot(dst_spot["tile"], sly_data)
        if not depot_spot:
            return json.dumps({"success": False, "error": "No depot spot found near either station"})

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])

        action_list.append({
            "action_type": "build_rail_station",
            "parameters": {
                "tile": src_spot["tile"], "num_platforms": 1,
                "platform_length": 3, "rail_type": 0,
            },
        })
        action_list.append({
            "action_type": "build_rail_station",
            "parameters": {
                "tile": dst_spot["tile"], "num_platforms": 1,
                "platform_length": 3, "rail_type": 0,
            },
        })
        action_list.append({
            "action_type": "connect_rail",
            "parameters": {
                "from_x": src_spot["x"], "from_y": src_spot["y"],
                "to_x": dst_spot["x"], "to_y": dst_spot["y"],
                "rail_type": 0,
            },
        })
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

        total_actions = 5 + wagon_count
        return json.dumps({
            "success": True,
            "actions_added": total_actions,
            "source_tile": src_spot["tile"],
            "dest_tile": dst_spot["tile"],
            "depot_tile": depot_spot["tile"],
            "wagons": wagon_count,
        })

    async def _find_station(
        self, industry_id: int, sly_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find a valid station spot near an industry, trying wider radius on failure."""
        for radius in (15, 20):
            try:
                result = await execute_tool(
                    "find_station_spot",
                    {
                        "industry_id": industry_id,
                        "platform_length": 3,
                        "rail_type": 0,
                        "radius": radius,
                        "max_results": 3,
                    },
                    sly_data,
                )
                spots = result.get("result", {}).get("spots", [])
                if spots:
                    return spots[0]
            except Exception:
                logger.warning(
                    "find_station_spot failed for industry %d radius %d",
                    industry_id, radius, exc_info=True,
                )
        return None

    async def _find_depot(
        self, near_tile: int, sly_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find a depot spot near existing track."""
        try:
            result = await execute_tool(
                "find_rail_depot_spot",
                {"tile": near_tile, "radius": 10, "max_results": 3},
                sly_data,
            )
            spots = result.get("result", {}).get("spots", [])
            if spots:
                return spots[0]
        except Exception:
            logger.warning("find_rail_depot_spot failed near tile %d", near_tile, exc_info=True)
        return None
