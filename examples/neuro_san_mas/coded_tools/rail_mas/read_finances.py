"""Coded tool: finance_data -- detailed financial data for the finance_advisor agent."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation


class ReadFinances(CodedTool):
    """Extracts financial data from sly_data observation for the finance advisor."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return "No game observation available."

        company = obs.get("company", {})
        vehicles = obs.get("vehicles", [])
        routes = obs.get("routes", [])

        total_route_profit = sum(r.get("profit_this_year", 0) for r in routes)
        total_vehicle_profit = sum(v.get("profit_this_year", 0) for v in vehicles)

        vehicle_costs: List[Dict[str, Any]] = []
        for v in vehicles:
            vehicle_costs.append({
                "id": v.get("id"),
                "profit_this_year": v.get("profit_this_year", 0),
                "profit_last_year": v.get("profit_last_year", 0),
                "age": v.get("age", 0),
                "running": v.get("running"),
            })

        route_profits: List[Dict[str, Any]] = []
        for r in routes:
            route_profits.append({
                "route_id": r.get("route_id"),
                "vehicle_count": r.get("vehicle_count"),
                "profit_this_year": r.get("profit_this_year", 0),
            })

        return json.dumps({
            "game_date": obs.get("game_date"),
            "balance": company.get("balance", 0),
            "loan": company.get("loan", 0),
            "max_loan": company.get("max_loan", 300000),
            "income": company.get("income", 0),
            "company_value": company.get("company_value", 0),
            "profit_last_year": company.get("profit_last_year", 0),
            "q1_income": company.get("q1_income"),
            "q1_expenses": company.get("q1_expenses"),
            "total_route_profit": total_route_profit,
            "total_vehicle_profit": total_vehicle_profit,
            "vehicle_count": len(vehicles),
            "route_count": len(routes),
            "vehicles": vehicle_costs,
            "routes": route_profits,
        }, indent=2)
