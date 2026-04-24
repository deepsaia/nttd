"""Coded tool: get_rail_types -- retrieves available rail track types from nttd."""

from __future__ import annotations

from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import query_gs
from rail_mas.sly_data_lock import SlyDataLock

_CACHE_KEY = "_cached_rail_types"


class GetRailTypes(CodedTool):
    """Calls nttd's get_rail_types observation tool via HTTP. Caches in sly_data."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        async with await SlyDataLock.get_lock(sly_data, f"{_CACHE_KEY}_lock"):
            cached = sly_data.get(_CACHE_KEY)
            if cached is not None:
                return cached

            result = await query_gs("get_rail_types", {}, sly_data)
            sly_data[_CACHE_KEY] = result

        return result
