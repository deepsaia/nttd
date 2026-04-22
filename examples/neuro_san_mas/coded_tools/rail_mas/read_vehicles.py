"""Coded tool: vehicle_data -- vehicles with orders and station IDs for vehicle_manager."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool


class ReadVehicles(CodedTool):
    """Extracts vehicle and station data from sly_data observation for the vehicle manager."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = sly_data.get("observation", {})
        if not obs:
            return "No game observation available."

        station_summary: List[Dict[str, Any]] = []
        for s in obs.get("stations", []):
            cargo_waiting = s.get("cargo_waiting", [])
            total_waiting = sum(c.get("waiting", 0) for c in cargo_waiting)
            station_summary.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "x": s.get("x"),
                "y": s.get("y"),
                "cargo_waiting_total": total_waiting,
                "cargo_waiting": [
                    {"cargo": c.get("cargo_label"), "amount": c.get("waiting")}
                    for c in cargo_waiting if c.get("waiting", 0) > 0
                ],
            })

        return json.dumps({
            "game_date": obs.get("game_date"),
            "vehicles": obs.get("vehicles", []),
            "stations": station_summary,
            "action_history": obs.get("action_history", [])[-15:],
            "previous_actions": obs.get("previous_actions", []),
        }, indent=2)
