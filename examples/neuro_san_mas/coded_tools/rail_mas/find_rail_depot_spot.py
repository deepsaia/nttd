"""Coded tool: find_rail_depot_spot -- finds valid depot locations adjacent to existing track."""

from __future__ import annotations

from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool


class FindRailDepotSpot(CodedTool):
    """Calls nttd's find_rail_depot_spot observation tool via HTTP."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {"tile": int(args["tile"])}
        if "radius" in args:
            params["radius"] = int(args["radius"])
        if "max_results" in args:
            params["max_results"] = int(args["max_results"])
        if "rail_type" in args:
            params["rail_type"] = int(args["rail_type"])

        result = await execute_tool("find_rail_depot_spot", params, sly_data)
        return result
