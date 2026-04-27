"""Coded tool: read_route_health -- route health assessment and context writer."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)

STALL_THRESHOLD_DAYS = 200


class ReadRouteHealth(CodedTool):
    """Reads routes/vehicles/stations, computes health, writes route_context."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            sly_data["route_context"] = _empty_context()
            sly_data["action_list"] = sly_data.get("action_list", [])
            return json.dumps({"total_routes": 0, "route_summary": []})

        routes: List[Dict[str, Any]] = obs.get("routes", [])
        vehicles: List[Dict[str, Any]] = obs.get("vehicles", [])
        game_date: int = obs.get("game_date", 0)

        vehicle_to_route, route_to_stations, route_to_vehicles = _build_mappings(routes)
        health = _classify_health(routes, game_date)
        unassigned = _find_unassigned_vehicles(vehicles, vehicle_to_route, route_to_stations)

        dismantle_route_ids = [rid for rid, h in health.items() if h == "stalled"]
        dismantle_vehicle_ids: List[int] = []
        for rid in dismantle_route_ids:
            dismantle_vehicle_ids.extend(route_to_vehicles.get(rid, []))

        route_context: Dict[str, Any] = {
            "vehicle_to_route": vehicle_to_route,
            "route_to_stations": route_to_stations,
            "route_to_vehicles": route_to_vehicles,
            "route_health": health,
            "dismantle_vehicle_ids": dismantle_vehicle_ids,
            "dismantle_route_ids": dismantle_route_ids,
            "unassigned_vehicles": unassigned,
            "game_date": game_date,
        }
        sly_data["route_context"] = route_context
        sly_data["action_list"] = sly_data.get("action_list", [])

        route_summary = [
            {
                "route_id": r.get("route_id", ""),
                "station_ids": r.get("station_ids", []),
                "status": r.get("status", ""),
                "health": health.get(r.get("route_id", ""), "unknown"),
                "vehicle_count": r.get("vehicle_count", 0),
                "profit_this_year": r.get("profit_this_year", 0),
                "profit_last_year": r.get("profit_last_year", 0),
            }
            for r in routes
        ]

        return json.dumps({
            "total_routes": len(routes),
            "route_summary": route_summary,
            "unassigned_vehicles": unassigned,
            "stalled_routes": dismantle_route_ids,
            "dismantle_vehicle_ids": dismantle_vehicle_ids,
        })


def _empty_context() -> Dict[str, Any]:
    return {
        "vehicle_to_route": {},
        "route_to_stations": {},
        "route_to_vehicles": {},
        "route_health": {},
        "dismantle_vehicle_ids": [],
        "dismantle_route_ids": [],
        "unassigned_vehicles": [],
        "game_date": 0,
    }


def _build_mappings(
    routes: List[Dict[str, Any]],
) -> tuple[Dict[int, str], Dict[str, List[int]], Dict[str, List[int]]]:
    vehicle_to_route: Dict[int, str] = {}
    route_to_stations: Dict[str, List[int]] = {}
    route_to_vehicles: Dict[str, List[int]] = {}

    for route in routes:
        rid = route.get("route_id", "")
        sids = route.get("station_ids", [])
        vids = route.get("vehicle_ids", [])
        route_to_stations[rid] = sids
        route_to_vehicles[rid] = vids
        for vid in vids:
            vehicle_to_route[vid] = rid

    return vehicle_to_route, route_to_stations, route_to_vehicles


def _classify_health(
    routes: List[Dict[str, Any]], game_date: int,
) -> Dict[str, str]:
    health: Dict[str, str] = {}
    for route in routes:
        rid = route.get("route_id", "")
        status = route.get("status", "")
        vehicle_count = route.get("vehicle_count", 0)

        if status != "active" or vehicle_count == 0:
            health[rid] = "incomplete"
            continue

        first_vehicle_at = route.get("first_vehicle_at", 0)
        age_days = game_date - first_vehicle_at if first_vehicle_at else 0

        if age_days < STALL_THRESHOLD_DAYS:
            health[rid] = "new"
            continue

        profit = route.get("profit_this_year", 0)
        profit_last = route.get("profit_last_year", 0)
        if profit <= 0 and profit_last <= 0:
            health[rid] = "stalled"
        else:
            health[rid] = "healthy"

    return health


def _find_unassigned_vehicles(
    vehicles: List[Dict[str, Any]],
    vehicle_to_route: Dict[int, str],
    route_to_stations: Dict[str, List[int]],
) -> List[Dict[str, Any]]:
    unassigned: List[Dict[str, Any]] = []
    for v in vehicles:
        if v.get("order_count", 0) >= 2:
            continue
        vid = v.get("id", -1)
        route_id = vehicle_to_route.get(vid)
        correct_stations = route_to_stations.get(route_id, []) if route_id else []
        unassigned.append({
            "id": vid,
            "correct_route_id": route_id,
            "correct_stations": correct_stations,
        })
    return unassigned
