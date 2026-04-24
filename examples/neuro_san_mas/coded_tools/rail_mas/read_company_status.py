"""Coded tool: company_status -- lightweight summary for the coordinator's decision tree."""

from __future__ import annotations

import json
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation


class ReadCompanyStatus(CodedTool):
    """Extracts decision-making fields from sly_data observation for the coordinator."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return "No game observation available."

        stations = obs.get("stations", [])
        vehicles = obs.get("vehicles", [])

        vehicle_summary = []
        for v in vehicles:
            vehicle_summary.append({
                "id": v.get("id"),
                "order_count": v.get("order_count"),
                "speed": v.get("current_speed", v.get("speed", 0)),
                "running": v.get("running"),
                "in_depot": v.get("in_depot"),
                "profit_this_year": v.get("profit_this_year", 0),
            })

        station_summary = []
        for s in stations:
            station_summary.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "x": s.get("x"),
                "y": s.get("y"),
            })

        routes = obs.get("routes", [])
        route_summary = []
        for r in routes:
            route_summary.append({
                "route_id": r.get("route_id"),
                "station_ids": r.get("station_ids"),
                "status": r.get("status"),
                "vehicle_ids": r.get("vehicle_ids", []),
                "vehicle_count": r.get("vehicle_count"),
                "depot_tile": r.get("depot_tile", 0),
                "profit_this_year": r.get("profit_this_year"),
            })

        route_planning = obs.get("route_planning", {})
        planning_summary = route_planning.get("summary", {})

        return json.dumps({
            "game_date": obs.get("game_date"),
            "company": obs.get("company", {}),
            "station_count": len(stations),
            "vehicle_count": len(vehicles),
            "vehicles": vehicle_summary,
            "stations": station_summary,
            "routes": route_summary,
            "unserved_cargo_routes": planning_summary.get("unserved_cargo_routes", 0),
            "route_status": obs.get("route_status", {}),
            "previous_actions": obs.get("previous_actions", []),
            "action_history": obs.get("action_history", [])[-15:],
        }, indent=2)
