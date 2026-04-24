"""Coded tool: build_route_actions -- validates station spots and emits track actions.

Cycle N work: finds valid station placements near source/dest industries via
live GS queries, then emits build_rail_station x2 + connect_rail.

Depot and vehicle purchasing happen in cycle N+1 (via build_depot_and_vehicles)
because find_rail_depot_spot requires existing adjacent track, which only
exists after connect_rail executes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import query_gs

logger = logging.getLogger(__name__)


class BuildRouteActions(CodedTool):
    """Validates station spots and builds station + track actions for a new route."""

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

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])
        actions_before = len(action_list)

        preferred_dir = self._preferred_direction(src_spot, dst_spot)
        src_dir = self._pick_direction(src_spot, preferred_dir)
        dst_dir = self._pick_direction(dst_spot, preferred_dir)

        action_list.append({
            "action_type": "build_rail_station",
            "parameters": {
                "tile": src_spot["tile"], "num_platforms": 1,
                "platform_length": 3, "rail_type": 0,
                "direction": src_dir,
            },
        })
        action_list.append({
            "action_type": "build_rail_station",
            "parameters": {
                "tile": dst_spot["tile"], "num_platforms": 1,
                "platform_length": 3, "rail_type": 0,
                "direction": dst_dir,
            },
        })
        src_edge_x, src_edge_y = self._track_edge(
            src_spot["x"], src_spot["y"], src_dir, 3,
            dst_spot["x"], dst_spot["y"],
        )
        dst_edge_x, dst_edge_y = self._track_edge(
            dst_spot["x"], dst_spot["y"], dst_dir, 3,
            src_spot["x"], src_spot["y"],
        )
        src_hint_x, src_hint_y = self._platform_end(
            src_spot["x"], src_spot["y"], src_dir, 3,
            dst_spot["x"], dst_spot["y"],
        )
        dst_hint_x, dst_hint_y = self._platform_end(
            dst_spot["x"], dst_spot["y"], dst_dir, 3,
            src_spot["x"], src_spot["y"],
        )
        action_list.append({
            "action_type": "connect_rail",
            "parameters": {
                "from_x": src_edge_x, "from_y": src_edge_y,
                "to_x": dst_edge_x, "to_y": dst_edge_y,
                "from_hint_x": src_hint_x, "from_hint_y": src_hint_y,
                "to_hint_x": dst_hint_x, "to_hint_y": dst_hint_y,
                "rail_type": 0,
            },
        })

        sly_data["action_list"] = action_list

        return json.dumps({
            "success": True,
            "actions_added": len(action_list) - actions_before,
            "source_tile": src_spot["tile"],
            "dest_tile": dst_spot["tile"],
            "engine_id": engine_id,
            "wagon_id": wagon_id,
            "num_wagons": num_wagons,
            "note": "Depot + vehicles will be built next cycle after track exists.",
        })

    @staticmethod
    def _preferred_direction(
        src_spot: Dict[str, Any], dst_spot: Dict[str, Any],
    ) -> int:
        """Compute station direction from the source-to-destination vector.

        NE-SW (dir=0): platforms extend along X axis, trains enter from NE/SW.
        NW-SE (dir=1): platforms extend along Y axis, trains enter from NW/SE.
        """
        dx = abs(dst_spot["x"] - src_spot["x"])
        dy = abs(dst_spot["y"] - src_spot["y"])
        return 0 if dx >= dy else 1

    @staticmethod
    def _pick_direction(spot: Dict[str, Any], preferred: int) -> int:
        """Pick the best direction for a station spot."""
        valid = spot.get("valid_directions", [0, 1])
        if preferred in valid:
            return preferred
        if valid:
            return valid[0]
        return preferred

    @staticmethod
    def _track_edge(
        sx: int, sy: int, direction: int, platform_length: int,
        other_x: int, other_y: int,
    ) -> tuple[int, int]:
        """Return the tile just past the station's track end facing the other station.

        For dir=0 (NE-SW), platform occupies (sx..sx+len-1, sy).
        Track ends: (sx-1, sy) and (sx+len, sy).
        For dir=1 (NW-SE), platform occupies (sx, sy..sy+len-1).
        Track ends: (sx, sy-1) and (sx, sy+len).
        """
        if direction == 0:
            end_lo_x = sx - 1
            end_hi_x = sx + platform_length
            if other_x >= sx:
                return end_hi_x, sy
            return end_lo_x, sy
        end_lo_y = sy - 1
        end_hi_y = sy + platform_length
        if other_y >= sy:
            return sx, end_hi_y
        return sx, end_lo_y

    @staticmethod
    def _platform_end(
        sx: int, sy: int, direction: int, platform_length: int,
        other_x: int, other_y: int,
    ) -> tuple[int, int]:
        """Return the last platform tile facing the other station.

        This is one tile inward from _track_edge, on the station platform itself.
        Used as a hint tile so connect_rail builds the first/last rail piece
        pointing back into the station.
        """
        if direction == 0:
            if other_x >= sx:
                return sx + platform_length - 1, sy
            return sx, sy
        if other_y >= sy:
            return sx, sy + platform_length - 1
        return sx, sy

    async def _find_station(
        self, industry_id: int, sly_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find a valid station spot near an industry, trying wider radius on failure."""
        for radius in (15, 20):
            try:
                result = await query_gs(
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
