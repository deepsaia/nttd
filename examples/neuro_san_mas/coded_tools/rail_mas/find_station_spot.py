"""Coded tool: find_station_spot -- validates rail station placement near an industry or town."""

from __future__ import annotations

import json
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool
from rail_mas.sly_data_lock import SlyDataLock


class FindStationSpot(CodedTool):
    """Calls nttd's find_station_spot observation tool via HTTP. Caches in sly_data."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if args.get("industry_id") is not None:
            params["industry_id"] = int(args["industry_id"])
        if args.get("town_id") is not None:
            params["town_id"] = int(args["town_id"])
        if args.get("platform_length") is not None:
            params["platform_length"] = int(args["platform_length"])
        if args.get("rail_type") is not None:
            params["rail_type"] = int(args["rail_type"])
        if args.get("radius") is not None:
            params["radius"] = int(args["radius"])
        if args.get("max_results") is not None:
            params["max_results"] = int(args["max_results"])

        cache_key = f"_cached_station_spot_{json.dumps(params, sort_keys=True)}"

        async with await SlyDataLock.get_lock(sly_data, f"{cache_key}_lock"):
            cached = sly_data.get(cache_key)
            if cached is not None:
                return cached

            result = await execute_tool("find_station_spot", params, sly_data)
            sly_data[cache_key] = result

        return result
