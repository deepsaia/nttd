"""Observation toolkit for gameloop agents.

Provides observation tools that agents can call during the decide phase
to query game state via the GameScript bridge. Each tool maps to a GS
query command and returns a JSON string result.

The toolkit produces OpenAI-format function schemas that any adapter
can convert to its native format. Tool execution goes through
admin_client.send_gamescript() — the same path used for action execution.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nttd.bridge.admin_client import AdminClient

logger = logging.getLogger(__name__)


# ── Tool definitions ──────────────────────────────────────────────────
# Each entry: (name, description, parameters_schema, default_params_fn)
# The default_params_fn fills in company_id where needed.

_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "get_towns",
        "description": "List all towns on the map: id, name, population, x, y, is_city.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_towns",
    },
    {
        "name": "get_town_info",
        "description": "Get detailed info about a specific town.",
        "parameters": {
            "type": "object",
            "properties": {"town_id": {"type": "integer", "description": "The town ID to query."}},
            "required": ["town_id"],
        },
        "gs_action": "get_town_info",
    },
    {
        "name": "get_industries",
        "description": "List all industries: id, name, type, location, production, acceptance.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_industries",
    },
    {
        "name": "get_industry_info",
        "description": "Get detailed info about a specific industry.",
        "parameters": {
            "type": "object",
            "properties": {"industry_id": {"type": "integer", "description": "The industry ID."}},
            "required": ["industry_id"],
        },
        "gs_action": "get_industry_info",
    },
    {
        "name": "get_companies",
        "description": "List all active companies: id, name, is_ai, color, manager.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_companies",
    },
    {
        "name": "get_company_finance",
        "description": "Get financial details: balance, loan, income, value, profit.",
        "parameters": {
            "type": "object",
            "properties": {"company_id": {"type": "integer", "description": "Company ID to query."}},
            "required": [],
        },
        "gs_action": "get_company_finance",
        "inject_company_id": True,
    },
    {
        "name": "get_engines",
        "description": "List purchasable engine types. vehicle_type: 0=train, 1=road, 2=ship, 3=aircraft.",
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle_type": {"type": "integer", "description": "0=train, 1=road, 2=ship, 3=aircraft.", "default": 1},
            },
            "required": [],
        },
        "gs_action": "get_engines",
        "inject_company_id": True,
    },
    {
        "name": "get_vehicles",
        "description": "List your vehicles: id, type, name, profit, depot status.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_vehicles",
        "inject_company_id": True,
    },
    {
        "name": "get_vehicle_info",
        "description": "Get detailed info about a specific vehicle.",
        "parameters": {
            "type": "object",
            "properties": {"vehicle_id": {"type": "integer", "description": "The vehicle ID."}},
            "required": ["vehicle_id"],
        },
        "gs_action": "get_vehicle_info",
    },
    {
        "name": "get_stations",
        "description": "List your stations: id, name, location, cargo waiting.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_stations",
        "inject_company_id": True,
    },
    {
        "name": "get_station_info",
        "description": "Get detailed info about a specific station.",
        "parameters": {
            "type": "object",
            "properties": {"station_id": {"type": "integer", "description": "The station ID."}},
            "required": ["station_id"],
        },
        "gs_action": "get_station_info",
    },
    {
        "name": "get_orders",
        "description": "Get the order list for a vehicle.",
        "parameters": {
            "type": "object",
            "properties": {"vehicle_id": {"type": "integer", "description": "Vehicle to query orders for."}},
            "required": ["vehicle_id"],
        },
        "gs_action": "get_orders",
    },
    {
        "name": "find_bus_stop_spots",
        "description": "Find road tiles near a town suitable for bus/truck stops.",
        "parameters": {
            "type": "object",
            "properties": {
                "town_id": {"type": "integer", "description": "Town to search near."},
                "max_results": {"type": "integer", "description": "Max spots to return.", "default": 5},
            },
            "required": ["town_id"],
        },
        "gs_action": "find_bus_stop_spots",
        "inject_company_id": True,
    },
    {
        "name": "find_depot_spots",
        "description": "Find road tiles near a town suitable for a road depot.",
        "parameters": {
            "type": "object",
            "properties": {
                "town_id": {"type": "integer", "description": "Town to search near."},
                "max_results": {"type": "integer", "description": "Max spots to return.", "default": 5},
            },
            "required": ["town_id"],
        },
        "gs_action": "find_depot_spots",
        "inject_company_id": True,
    },
    {
        "name": "scan_town_area",
        "description": "Scan the area around a town for buildable tiles.",
        "parameters": {
            "type": "object",
            "properties": {"town_id": {"type": "integer", "description": "Town to scan around."}},
            "required": ["town_id"],
        },
        "gs_action": "scan_town_area",
    },
    {
        "name": "get_tile_info",
        "description": "Get terrain and infrastructure details for a map tile. Tile ID = y * map_width + x.",
        "parameters": {
            "type": "object",
            "properties": {"tile": {"type": "integer", "description": "Tile ID (y * map_width + x)."}},
            "required": ["tile"],
        },
        "gs_action": "get_tile_info",
    },
    {
        "name": "get_map_size",
        "description": "Get the map dimensions (width and height).",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_map_size",
    },
    {
        "name": "get_cargo_types",
        "description": "List all cargo types in the game: id, label, name.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_cargo_types",
    },
    {
        "name": "get_subsidies",
        "description": "List active subsidies: cargo, source, destination, value, remaining years.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_subsidies",
    },
    {
        "name": "get_rail_types",
        "description": "List available rail types.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_rail_types",
    },
    {
        "name": "get_road_types",
        "description": "List available road types.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_road_types",
    },
    {
        "name": "get_bridge_types",
        "description": "List available bridge types with speed limits and costs.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_bridge_types",
    },
    {
        "name": "get_airport_types",
        "description": "List available airport types with dimensions and capacities.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_airport_types",
    },
    {
        "name": "get_groups",
        "description": "List vehicle groups for your company.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_groups",
        "inject_company_id": True,
    },
    {
        "name": "get_date",
        "description": "Get the current in-game date.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_date",
    },
    {
        "name": "get_town_rating",
        "description": "Get the local authority rating for your company in a town.",
        "parameters": {
            "type": "object",
            "properties": {"town_id": {"type": "integer", "description": "Town to check."}},
            "required": ["town_id"],
        },
        "gs_action": "get_town_rating",
        "inject_company_id": True,
    },
]


class ObservationToolkit:
    """Provides observation tools for a gameloop agent.

    Tools are read-only GS queries that agents can call during the
    decide phase to gather information before choosing actions.
    """

    def __init__(self, admin_client: AdminClient, company_id: int) -> None:
        self._client = admin_client
        self._company_id = company_id
        self._tool_map: dict[str, dict[str, Any]] = {t["name"]: t for t in _TOOL_DEFS}

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI function-calling format."""
        schemas: list[dict[str, Any]] = []
        for tool_def in _TOOL_DEFS:
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool_def["name"],
                    "description": tool_def["description"],
                    "parameters": tool_def["parameters"],
                },
            })
        return schemas

    def get_tool_names(self) -> list[str]:
        """Get list of available tool names."""
        return [t["name"] for t in _TOOL_DEFS]

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name and return JSON string result.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments from the LLM.

        Returns:
            JSON string with the tool result.
        """
        tool_def = self._tool_map.get(tool_name)
        if tool_def is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        gs_action = tool_def["gs_action"]
        params = dict(arguments)

        # Inject company_id for tools that need it
        if tool_def.get("inject_company_id") and "company_id" not in params:
            params["company_id"] = self._company_id

        try:
            result = await self._client.send_gamescript(gs_action, params, timeout=15.0)
            if result.get("success"):
                return json.dumps(result.get("result", {}), indent=2)
            return json.dumps({"error": result.get("error", "GS query failed")})
        except Exception as exc:
            logger.warning("Tool %s execution failed: %s", tool_name, exc)
            return json.dumps({"error": str(exc)})
