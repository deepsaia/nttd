"""Coded tool: set_loan_action -- prepends a set_loan action to sly_data."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

logger = logging.getLogger(__name__)


class SetLoanAction(CodedTool):
    """Creates a set_loan action and prepends it to sly_data["action_list"]."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        amount: int = args["amount"]

        action_list: List[Dict[str, Any]] = sly_data.get("action_list", [])
        action_list.insert(0, {
            "action_type": "set_loan",
            "parameters": {"amount": amount},
        })
        sly_data["action_list"] = action_list

        return f"Set loan to {amount} (prepended to action list, {len(action_list)} total actions)"
