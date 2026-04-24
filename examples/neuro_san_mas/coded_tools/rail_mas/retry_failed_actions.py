"""Coded tool: retry_failed_actions -- retries failed builds with adjustments."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import query_gs
from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class RetryFailedActions(CodedTool):
    """Reads previous_actions from observation, retries failures with adjusted parameters."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"retried": [], "failed_count": 0})

        previous_actions: List[Dict[str, Any]] = obs.get("previous_actions", [])
        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])
        retries: List[str] = []

        for prev in previous_actions:
            if prev.get("status") != "failed":
                continue

            action_type = prev.get("action", "")
            params = prev.get("parameters", {})
            if not isinstance(params, dict):
                params = {}
            error = prev.get("error", "")

            if action_type == "build_rail_station":
                self._retry_station(params, error, action_list, retries)
            elif action_type == "build_rail_depot":
                await self._retry_depot(params, action_list, retries, sly_data)
            elif action_type == "buy_vehicle":
                retries.append(f"buy_vehicle failed ({error}), will retry next cycle")

        sly_data["action_list"] = action_list
        failed_count = sum(1 for p in previous_actions if p.get("status") == "failed")
        return json.dumps({"retried": retries, "failed_count": failed_count})

    def _retry_station(
        self,
        params: Dict[str, Any],
        error: str,
        action_list: List[Dict[str, Any]],
        retries: List[str],
    ) -> None:
        """Retry station build at an offset tile."""
        tile = params.get("tile")
        if tile is None:
            return
        action_list.append({
            "action_type": "build_rail_station",
            "parameters": {
                "tile": tile + 1,
                "num_platforms": params.get("num_platforms", 1),
                "platform_length": params.get("platform_length", 3),
                "rail_type": params.get("rail_type", 0),
            },
        })
        retries.append(f"station at tile {tile + 1} (was {tile}, error: {error})")

    async def _retry_depot(
        self,
        params: Dict[str, Any],
        action_list: List[Dict[str, Any]],
        retries: List[str],
        sly_data: Dict[str, Any],
    ) -> None:
        """Retry depot build by searching for a new spot."""
        tile = params.get("tile")
        if tile is None:
            return
        try:
            depot_result = await query_gs(
                "find_rail_depot_spot",
                {"tile": tile, "radius": 15},
                sly_data,
            )
            spots = depot_result.get("result", [])
            if spots:
                spot = spots[0]
                action_list.append({
                    "action_type": "build_rail_depot",
                    "parameters": {
                        "tile": spot["tile"],
                        "direction": spot.get("depot_direction", 0),
                    },
                })
                retries.append(f"depot at tile {spot['tile']}")
        except Exception:
            logger.warning("Failed to find alternate depot spot for retry", exc_info=True)
