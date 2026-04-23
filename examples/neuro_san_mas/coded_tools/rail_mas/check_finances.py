"""Coded tool: check_finances -- returns company financial status and affordability."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)

SAFETY_MARGIN = 10000


class CheckFinances(CodedTool):
    """Returns company financial status and whether a given cost is affordable."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"error": "No observation available"})

        company: Dict[str, Any] = obs.get("company", {})
        estimated_cost = args.get("estimated_cost", 0)

        balance = company.get("balance", 0)
        loan = company.get("loan", 0)
        max_loan = company.get("max_loan", 300000)
        income = company.get("income", 0)

        loan_room = max_loan - loan
        can_afford = balance >= estimated_cost + SAFETY_MARGIN
        shortfall = max(0, estimated_cost + SAFETY_MARGIN - balance)
        can_afford_with_loan = shortfall <= loan_room

        return json.dumps({
            "balance": balance,
            "loan": loan,
            "max_loan": max_loan,
            "income": income,
            "loan_room": loan_room,
            "estimated_cost": estimated_cost,
            "safety_margin": SAFETY_MARGIN,
            "can_afford": can_afford,
            "shortfall": shortfall,
            "can_afford_with_loan": can_afford_with_loan,
        })
