"""Coded tool: get_engines -- retrieves available train engines from nttd."""

from __future__ import annotations

from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool


class GetEngines(CodedTool):
    """Calls nttd's get_engines observation tool via HTTP."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {"vehicle_type": int(args.get("vehicle_type", 0))}
        result = await execute_tool("get_engines", params, sly_data)
        return result
