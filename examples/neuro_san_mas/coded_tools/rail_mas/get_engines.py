"""Coded tool: get_engines -- retrieves available train engines from nttd."""

from __future__ import annotations

from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool
from rail_mas.sly_data_lock import SlyDataLock


class GetEngines(CodedTool):
    """Calls nttd's get_engines observation tool via HTTP. Caches in sly_data."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        vtype = int(args.get("vehicle_type", 0))
        cache_key = f"_cached_engines_{vtype}"

        async with await SlyDataLock.get_lock(sly_data, f"{cache_key}_lock"):
            cached = sly_data.get(cache_key)
            if cached is not None:
                return cached

            params: Dict[str, Any] = {"vehicle_type": vtype}
            result = await execute_tool("get_engines", params, sly_data)
            sly_data[cache_key] = result

        return result
