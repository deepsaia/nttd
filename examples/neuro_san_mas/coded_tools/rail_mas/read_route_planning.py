"""Coded tool: route_planning_data -- unserved routes and industries for route_scout."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool


class ReadRoutePlanning(CodedTool):
    """Extracts route planning data from sly_data observation for the route scout."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = sly_data.get("observation", {})
        if not obs:
            return "No game observation available."

        station_summary: List[Dict[str, Any]] = []
        for s in obs.get("stations", []):
            station_summary.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "x": s.get("x"),
                "y": s.get("y"),
            })

        station_locs = {(s.get("x", 0), s.get("y", 0)) for s in obs.get("stations", [])}
        catchment_radius = 10

        all_industries: List[Dict[str, Any]] = []
        for ind in obs.get("industries", []):
            prod = ind.get("production", [])
            total_production = sum(p.get("last_month", 0) for p in prod)
            top_prod = [
                {"cargo": p.get("cargo_label"), "monthly": p.get("last_month")}
                for p in prod if p.get("last_month", 0) > 0
            ]
            accepted = [a.get("cargo_label") for a in ind.get("accepted", [])]
            ix, iy = ind.get("x", 0), ind.get("y", 0)
            served = any(
                abs(sx - ix) + abs(sy - iy) <= catchment_radius
                for sx, sy in station_locs
            )
            all_industries.append({
                "id": ind.get("id"),
                "name": ind.get("name"),
                "type": ind.get("type_name"),
                "x": ix,
                "y": iy,
                "is_raw": ind.get("is_raw"),
                "produces": top_prod,
                "accepts": accepted,
                "served": served,
                "_total_prod": total_production,
            })

        unconnected = [i for i in all_industries if not i["served"] and i["_total_prod"] > 0]
        unconnected.sort(key=lambda i: i["_total_prod"], reverse=True)
        industry_summary: List[Dict[str, Any]] = []
        for ind in unconnected[:5]:
            ind.pop("_total_prod", None)
            industry_summary.append(ind)

        route_planning = obs.get("route_planning", {})

        subsidies: List[Dict[str, Any]] = []
        for s in obs.get("subsidies", []):
            subsidies.append({
                "id": s.get("id"),
                "cargo": s.get("cargo_label"),
                "from": s.get("src_name"),
                "to": s.get("dst_name"),
            })

        return json.dumps({
            "game_date": obs.get("game_date"),
            "balance": obs.get("company", {}).get("balance", 0),
            "top_unserved_cargo": route_planning.get("top_unserved_cargo", [])[:5],
            "top_unserved_towns": route_planning.get("top_unserved_towns", [])[:5],
            "planning_summary": route_planning.get("summary", {}),
            "existing_routes": route_planning.get("existing_routes", []),
            "industries": industry_summary,
            "existing_stations": station_summary,
            "subsidies": subsidies,
        }, indent=2)
