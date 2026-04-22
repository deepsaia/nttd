"""Coded tool: find_rail_depot_spot -- finds valid depot locations adjacent to existing track."""

from __future__ import annotations

import json
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool
from rail_mas.sly_data_lock import SlyDataLock


class FindRailDepotSpot(CodedTool):
    """Calls nttd's find_rail_depot_spot observation tool via HTTP. Caches in sly_data."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        if args.get("tile") is None:
            return {"error": "tile parameter is required"}
        params: Dict[str, Any] = {"tile": int(args["tile"])}
        if args.get("radius") is not None:
            params["radius"] = int(args["radius"])
        if args.get("max_results") is not None:
            params["max_results"] = int(args["max_results"])
        if args.get("rail_type") is not None:
            params["rail_type"] = int(args["rail_type"])

        cache_key = f"_cached_depot_spot_{json.dumps(params, sort_keys=True)}"

        async with await SlyDataLock.get_lock(sly_data, f"{cache_key}_lock"):
            cached = sly_data.get(cache_key)
            if cached is not None:
                return cached

            result = await execute_tool("find_rail_depot_spot", params, sly_data)
            sly_data[cache_key] = result

        return result
