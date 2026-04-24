"""Coded tool: build_depot_and_vehicles -- builds depot and buys engine + wagons.

Cycle N+1 work: after stations + track exist from the previous cycle,
finds a valid depot spot adjacent to existing track, then emits
build_rail_depot + build_train (engine + wagons assembled atomically).

Auto-selects the correct wagon type by matching station cargo against
the engine list.  Enforces 1-train-per-route (no signals yet).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.cargo_matcher import CargoMatcher
from rail_mas.nttd_client import query_gs
from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class BuildDepotAndVehicles(CodedTool):
    """Finds depot spot near track, builds depot, buys engine + wagons."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        station_tile: int = args["station_tile"]
        engine_id: int = args["engine_id"]
        caller_wagon_id: Optional[int] = args.get("wagon_id")
        num_wagons: int = args.get("num_wagons", 3)

        obs = get_observation(sly_data)

        if obs and self._route_has_vehicle(station_tile, obs, sly_data):
            return json.dumps({
                "success": False,
                "error": "Route already has a vehicle. Skipping (no signals, 1 train per route).",
            })

        wagon_id, cargo_id = self._auto_select_wagon(
            station_tile, caller_wagon_id, obs, sly_data,
        )

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
        if cargo_id is not None:
            params["cargo_id"] = cargo_id

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
            "wagon_id": wagon_id,
            "cargo_id": cargo_id,
            "auto_selected": wagon_id != caller_wagon_id,
            "note": "Orders + start will be added next cycle after vehicle appears in observation.",
        })

    def _route_has_vehicle(
        self,
        station_tile: int,
        obs: Dict[str, Any],
        sly_data: Dict[str, Any],
    ) -> bool:
        """Check if the route already has a vehicle, depot vehicle, or pending build."""
        map_width = obs.get("map_size", {}).get("x", 256)
        sx = station_tile % map_width
        sy = station_tile // map_width

        station_id = self._station_id_for_tile(station_tile, obs)
        if station_id is not None:
            for route in obs.get("routes", []):
                if station_id in route.get("station_ids", []):
                    if route.get("vehicle_count", 0) >= 1:
                        return True

        for v in obs.get("vehicles", []):
            vx, vy = v.get("x", 0), v.get("y", 0)
            if abs(vx - sx) + abs(vy - sy) <= 15:
                return True

        for action in sly_data.get("action_list", []):
            if action.get("action_type") != "build_train":
                continue
            existing_tile = action.get("parameters", {}).get("depot_tile", -1)
            ex = existing_tile % map_width
            ey = existing_tile // map_width
            if abs(ex - sx) + abs(ey - sy) <= 20:
                return True
        return False

    def _auto_select_wagon(
        self,
        station_tile: int,
        caller_wagon_id: Optional[int],
        obs: Optional[Dict[str, Any]],
        sly_data: Dict[str, Any],
    ) -> tuple[Optional[int], Optional[int]]:
        """Return (wagon_id, cargo_id) by matching station cargo to engines.

        Falls back to caller_wagon_id if auto-selection fails.
        """
        if not obs:
            return caller_wagon_id, None

        station_id = self._station_id_for_tile(station_tile, obs)
        if station_id is None:
            return caller_wagon_id, None

        stations: List[Dict[str, Any]] = obs.get("stations", [])
        cargo_label = CargoMatcher.get_station_cargo(station_id, stations)
        if not cargo_label:
            return caller_wagon_id, None

        engines = self._get_engines(sly_data)
        if not engines:
            return caller_wagon_id, None

        wagon = CargoMatcher.select_wagon(cargo_label, engines)
        cargo_id = CargoMatcher.cargo_label_to_id(cargo_label, engines)

        if wagon:
            return wagon["id"], cargo_id
        return caller_wagon_id, cargo_id

    def _station_id_for_tile(
        self, tile: int, obs: Dict[str, Any],
    ) -> Optional[int]:
        """Find station ID from observation matching a tile value."""
        for s in obs.get("stations", []):
            if s.get("tile") == tile:
                return s.get("id")
        map_width = obs.get("map_size", {}).get("x", 256)
        tile_x = tile % map_width
        tile_y = tile // map_width
        for s in obs.get("stations", []):
            sx, sy = s.get("x", 0), s.get("y", 0)
            if abs(sx - tile_x) + abs(sy - tile_y) <= 5:
                return s.get("id")
        return None

    def _get_engines(self, sly_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Read cached engine list from sly_data if available."""
        cached = sly_data.get("_cached_engines_0")
        if cached:
            result = cached if isinstance(cached, list) else cached.get("result", [])
            return result
        return []

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
