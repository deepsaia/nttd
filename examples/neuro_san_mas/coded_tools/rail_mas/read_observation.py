"""Coded tool that reads the current game observation from sly_data.

nttd sends the full observation as part of the MAS HTTP request payload.
The MAS HTTP adapter puts this into sly_data["observation"] before the
agent network runs. This coded tool surfaces it to the chat stream
so LLM agents can reason about it. Supports a "summary" mode that
extracts only the key decision-making fields to reduce token usage.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool


class ReadObservation(CodedTool):
    """Surfaces the nttd game observation from sly_data into the chat stream."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        observation = sly_data.get("observation")
        if observation is None:
            return "No game observation available in sly_data."

        if isinstance(observation, str):
            try:
                observation = json.loads(observation)
            except (json.JSONDecodeError, TypeError):
                return observation

        detail_level = (args.get("detail_level") or "full").lower()
        if detail_level == "summary":
            return json.dumps(_build_summary(observation), indent=2)

        return json.dumps(observation, indent=2)


def _build_summary(obs: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key decision-making fields from the full observation."""
    companies = obs.get("companies", [])
    stations = obs.get("stations", [])
    vehicles = obs.get("vehicles", [])
    route_planning = obs.get("route_planning", {})

    company_summary: List[Dict[str, Any]] = []
    for c in companies:
        company_summary.append({
            "id": c.get("id"),
            "balance": c.get("balance"),
            "loan": c.get("loan"),
            "revenue": c.get("revenue"),
        })

    station_summary: List[Dict[str, Any]] = []
    for s in stations:
        station_summary.append({
            "id": s.get("id"),
            "name": s.get("name"),
            "tile": s.get("tile"),
            "x": s.get("x"),
            "y": s.get("y"),
            "cargo_waiting": s.get("cargo_waiting"),
        })

    vehicle_summary: List[Dict[str, Any]] = []
    for v in vehicles:
        vehicle_summary.append({
            "id": v.get("id"),
            "name": v.get("name"),
            "speed": v.get("current_speed", v.get("speed")),
            "order_count": v.get("order_count"),
            "profit_this_year": v.get("profit_this_year"),
            "age_days": v.get("age_days", v.get("age")),
            "location_tile": v.get("location_tile", v.get("tile")),
        })

    top_routes = route_planning.get("top_unserved_cargo", [])[:5]

    action_history = obs.get("action_history", [])
    recent_history: List[Dict[str, Any]] = []
    for a in action_history[-15:]:
        recent_history.append({
            "action_type": a.get("action_type"),
            "success": a.get("success"),
            "error": a.get("error"),
            "result": a.get("result"),
        })

    previous_actions = obs.get("previous_actions", [])

    return {
        "game_date": obs.get("game_date"),
        "station_count": len(stations),
        "vehicle_count": len(vehicles),
        "companies": company_summary,
        "stations": station_summary,
        "vehicles": vehicle_summary,
        "top_unserved_routes": top_routes,
        "action_history_recent": recent_history,
        "previous_actions": previous_actions,
    }
