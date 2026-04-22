"""Coded tool: infrastructure_data -- stations and build history for infrastructure_builder."""

from __future__ import annotations

import json
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool


class ReadInfrastructure(CodedTool):
    """Extracts station and action history data from sly_data for the infrastructure builder."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = sly_data.get("observation", {})
        if not obs:
            return "No game observation available."

        return json.dumps({
            "game_date": obs.get("game_date"),
            "company": obs.get("company", {}),
            "stations": obs.get("stations", []),
            "action_history": obs.get("action_history", [])[-15:],
            "previous_actions": obs.get("previous_actions", []),
        }, indent=2)
