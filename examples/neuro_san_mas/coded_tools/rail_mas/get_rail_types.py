"""Coded tool: get_rail_types -- retrieves available rail track types from nttd."""

from __future__ import annotations

from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.nttd_client import execute_tool


class GetRailTypes(CodedTool):
    """Calls nttd's get_rail_types observation tool via HTTP."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        result = await execute_tool("get_rail_types", {}, sly_data)
        return result
