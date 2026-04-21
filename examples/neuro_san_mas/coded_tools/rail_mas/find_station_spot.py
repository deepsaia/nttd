"""Coded tool: find_station_spot -- validates rail station placement near an industry or town."""

from __future__ import annotations

from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool


class FindStationSpot(CodedTool):
    """Calls nttd's find_station_spot observation tool via HTTP."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if "industry_id" in args:
            params["industry_id"] = int(args["industry_id"])
        if "town_id" in args:
            params["town_id"] = int(args["town_id"])
        if "platform_length" in args:
            params["platform_length"] = int(args["platform_length"])
        if "rail_type" in args:
            params["rail_type"] = int(args["rail_type"])
        if "radius" in args:
            params["radius"] = int(args["radius"])
        if "max_results" in args:
            params["max_results"] = int(args["max_results"])

        result = await execute_tool("find_station_spot", params, sly_data)
        return result
