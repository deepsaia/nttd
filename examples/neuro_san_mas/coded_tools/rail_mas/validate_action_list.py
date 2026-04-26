"""Coded tool: validate_action_list -- deduplicates and enforces safety rules."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Set

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)

RAIL_ACTIONS: Set[str] = {
    "set_loan",
    "build_rail_station",
    "build_rail_depot",
    "build_rail_signal",
    "connect_rail",
    "buy_vehicle",
    "build_train",
    "add_order",
    "start_vehicle",
    "clone_vehicle",
    "refit_vehicle",
}

DISRUPTIVE_ACTIONS: Set[str] = {
    "send_to_depot",
    "stop_vehicle",
    "remove_order",
    "sell_vehicle",
}


class ValidateActionList(CodedTool):
    """Deduplicates, filters unknown actions, blocks disruptive actions on running trains."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"validated": 0, "removed": ["no observation available"]})

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])
        if not action_list:
            return json.dumps({"validated": 0, "removed": []})

        protected_vehicle_ids = self._get_protected_vehicles(obs)

        validated: List[Dict[str, Any]] = []
        removed: List[str] = []
        seen: set[str] = set()

        for action in action_list:
            action_type = action.get("action_type", "")
            params = action.get("parameters", {})

            fingerprint = json.dumps({"t": action_type, "p": params}, sort_keys=True)
            if fingerprint in seen:
                removed.append(f"duplicate {action_type}")
                continue
            seen.add(fingerprint)

            if action_type in DISRUPTIVE_ACTIONS:
                vid = params.get("vehicle_id")
                if vid in protected_vehicle_ids:
                    removed.append(f"{action_type} blocked for running vehicle {vid}")
                    continue

            if action_type not in RAIL_ACTIONS:
                removed.append(f"unknown action {action_type}")
                continue

            validated.append(action)

        validated = self._cap_orders_per_vehicle(validated, removed)
        validated = self._cap_build_train(validated, removed)
        sly_data["action_list"] = validated

        return json.dumps({
            "validated": len(validated),
            "removed": removed,
            "total_before": len(action_list),
        })

    @staticmethod
    def _cap_orders_per_vehicle(
        actions: List[Dict[str, Any]], removed: List[str],
    ) -> List[Dict[str, Any]]:
        """Allow at most 2 add_order actions per vehicle."""
        order_count: Dict[int, int] = {}
        result: List[Dict[str, Any]] = []
        for action in actions:
            if action.get("action_type") == "add_order":
                vid = action.get("parameters", {}).get("vehicle_id")
                if vid is not None:
                    order_count[vid] = order_count.get(vid, 0) + 1
                    if order_count[vid] > 2:
                        removed.append(f"excess add_order for vehicle {vid}")
                        continue
            result.append(action)
        return result

    @staticmethod
    def _cap_build_train(
        actions: List[Dict[str, Any]], removed: List[str],
    ) -> List[Dict[str, Any]]:
        """Allow at most 1 build_train per cycle."""
        train_count = 0
        result: List[Dict[str, Any]] = []
        for action in actions:
            if action.get("action_type") == "build_train":
                train_count += 1
                if train_count > 1:
                    removed.append("excess build_train (max 1 per cycle)")
                    continue
            result.append(action)
        return result

    def _get_protected_vehicles(self, obs: Dict[str, Any]) -> Set[int]:
        """Return IDs of vehicles with 2+ orders that must not be disrupted."""
        protected: Set[int] = set()
        for v in obs.get("vehicles", []):
            if v.get("order_count", 0) >= 2:
                vid = v.get("id")
                if vid is not None:
                    protected.add(vid)
        return protected
