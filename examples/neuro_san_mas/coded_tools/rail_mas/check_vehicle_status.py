"""Coded tool: check_vehicle_status -- reads vehicle and station status from observation."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Set

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

        served_sids = self._served_station_ids(obs)
        needs_depot_and_vehicle = bool(orphan_ids) and len(incomplete) == 0

        station_tiles: Dict[int, int] = {}
        if orphan_ids:
            for s in obs.get("stations", []):
                sid = s.get("id")
                if sid in orphan_ids:
                    tile = s.get("tile", 0)
                    if tile > 0:
                        station_tiles[sid] = tile

        assignments = self._match_vehicles_to_orphans(
            incomplete, orphan_ids, obs.get("stations", []), served_sids,
        )

        sly_data["action_list"] = sly_data.get("action_list", [])

        return json.dumps({
            "incomplete_vehicles": [
                {"id": v.get("id"), "order_count": v.get("order_count", 0),
                 "speed": v.get("speed", 0), "in_depot": v.get("in_depot", False),
                 "x": v.get("x", 0), "y": v.get("y", 0)}
                for v in incomplete
            ],
            "orphan_station_ids": orphan_ids,
            "orphan_station_tiles": station_tiles,
            "needs_depot_and_vehicle": needs_depot_and_vehicle,
            "suggested_assignments": assignments,
            "total_vehicles": len(vehicles),
            "running_vehicles": len(vehicles) - len(incomplete),
            "failed_actions": failed_actions,
        })

    @staticmethod
    def _served_station_ids(obs: Dict[str, Any]) -> Set[int]:
        """Return station IDs that belong to routes with at least 1 vehicle."""
        served: Set[int] = set()
        for route in obs.get("routes", []):
            if route.get("vehicle_count", 0) >= 1:
                for sid in route.get("station_ids", []):
                    served.add(sid)
        return served

    @staticmethod
    def _match_vehicles_to_orphans(
        incomplete: List[Dict[str, Any]],
        orphan_ids: List[int],
        stations: List[Dict[str, Any]],
        served_sids: Set[int],
    ) -> List[Dict[str, Any]]:
        """Match incomplete vehicles to unserved orphan station pairs.

        Uses greedy closest-pair matching: for each incomplete vehicle,
        find the nearest orphan station pair that isn't already served.
        """
        if not incomplete or len(orphan_ids) < 2:
            return []

        station_map: Dict[int, Dict[str, Any]] = {
            s.get("id", -1): s for s in stations
        }

        unserved_orphans = [oid for oid in orphan_ids if oid not in served_sids]
        if len(unserved_orphans) < 2:
            return []

        pairs: List[tuple[int, int, int, int, int, int]] = []
        used: Set[int] = set()
        for i, sid1 in enumerate(unserved_orphans):
            if sid1 in used:
                continue
            s1 = station_map.get(sid1, {})
            s1x, s1y = s1.get("x", 0), s1.get("y", 0)
            best_dist = float("inf")
            best_sid2 = -1
            for sid2 in unserved_orphans:
                if sid2 == sid1 or sid2 in used:
                    continue
                s2 = station_map.get(sid2, {})
                dist = abs(s1x - s2.get("x", 0)) + abs(s1y - s2.get("y", 0))
                if dist < best_dist:
                    best_dist = dist
                    best_sid2 = sid2
            if best_sid2 >= 0:
                s2 = station_map.get(best_sid2, {})
                pairs.append((sid1, s1x, s1y, best_sid2, s2.get("x", 0), s2.get("y", 0)))
                used.add(sid1)
                used.add(best_sid2)

        assignments: List[Dict[str, Any]] = []
        used_vehicles: Set[int] = set()
        for src_sid, sx, sy, dst_sid, dx, dy in pairs:
            mid_x = (sx + dx) // 2
            mid_y = (sy + dy) // 2
            best_vid = -1
            best_dist = float("inf")
            for v in incomplete:
                vid = v.get("id", -1)
                if vid in used_vehicles:
                    continue
                vx, vy = v.get("x", 0), v.get("y", 0)
                dist = abs(vx - mid_x) + abs(vy - mid_y)
                if dist < best_dist:
                    best_dist = dist
                    best_vid = vid
            if best_vid >= 0:
                assignments.append({
                    "vehicle_id": best_vid,
                    "src_station_id": src_sid,
                    "dst_station_id": dst_sid,
                })
                used_vehicles.add(best_vid)

        return assignments
