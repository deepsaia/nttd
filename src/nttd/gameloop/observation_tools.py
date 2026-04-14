"""Observation toolkit for gameloop agents.

Provides observation tools that agents can call during the decide phase
to query game state via the GameScript bridge. Each tool maps to a GS
query command and returns a JSON string result.

The toolkit produces OpenAI-format function schemas that any adapter
can convert to its native format. Tool execution goes through
admin_client.send_gamescript() -- the same path used for action execution.
Pathfinding is the exception: it uses the Python A* pathfinder directly.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from nttd.bridge.admin_client import AdminClient

logger = logging.getLogger(__name__)

# Maps agent_type -> set of vehicle type strings visible to that agent
AGENT_VEHICLE_TYPES: dict[str, set[str]] = {
    "road": {"road"},
    "rail": {"train"},
    "air": {"aircraft"},
    "water": {"ship"},
    "general": {"train", "road", "ship", "aircraft"},
}

# Maps agent_type -> station filter predicate
AGENT_STATION_FILTERS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "road": lambda s: s.get("has_bus") or s.get("has_truck"),
    "rail": lambda s: s.get("has_rail"),
    "air": lambda s: s.get("has_airport"),
    "water": lambda s: s.get("has_dock"),
    "general": lambda s: True,
}


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
        "description": (
            "List purchasable engines. Returns id, name, cargo_label, capacity, price."
            " For road: cargo_label=PASS means bus, others are trucks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle_type": {
                    "type": "integer",
                    "description": "0=train, 1=road, 2=ship, 3=aircraft.",
                    "default": 1,
                },
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
        "description": (
            "Find road tiles near a town suitable for bus/truck stops."
            " Returns tile, direction (pass to build_road_stop), and cargo_acceptance."
        ),
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
        "name": "find_airport_spots",
        "description": (
            "Find tiles near a town where an airport can be built (dry-run validated)."
            " Returns tile, x, y, cargo_acceptance for each spot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "town_id": {"type": "integer", "description": "Town to search near."},
                "airport_type": {
                    "type": "integer",
                    "description": "Airport type (0=small, 1=city, 2=metro). Default 0.",
                    "default": 0,
                },
                "max_results": {"type": "integer", "description": "Max spots to return.", "default": 5},
            },
            "required": ["town_id"],
        },
        "gs_action": "find_airport_spots",
        "inject_company_id": True,
    },
    {
        "name": "find_dock_spots",
        "description": (
            "Find coast tiles near a town where a dock can be built (dry-run validated)."
            " Returns tile, x, y, cargo_acceptance for each spot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "town_id": {"type": "integer", "description": "Town to search near."},
                "max_results": {"type": "integer", "description": "Max spots to return.", "default": 5},
            },
            "required": ["town_id"],
        },
        "gs_action": "find_dock_spots",
        "inject_company_id": True,
    },
    {
        "name": "find_flat_spots",
        "description": (
            "Find flat buildable tiles near a given tile."
            " Useful for rail depots/stations near industries."
            " For rail stations, pass station_test=true and platform_length"
            " to dry-run validate that a station can actually be built there."
            " Use required_cargo to filter for tiles that produce a specific cargo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tile": {"type": "integer", "description": "Center tile ID (y * map_width + x)."},
                "radius": {"type": "integer", "description": "Search radius. Default 10.", "default": 10},
                "min_size": {
                    "type": "integer",
                    "description": "Minimum flat square size (e.g. 3 for a 3-tile station). Default 1.",
                    "default": 1,
                },
                "max_results": {"type": "integer", "description": "Max spots to return.", "default": 10},
                "station_test": {
                    "type": "boolean",
                    "description": "Dry-run test BuildRailStation at each spot. Default false.",
                    "default": False,
                },
                "platform_length": {
                    "type": "integer",
                    "description": "Station platform length for dry-run test. Default 3.",
                    "default": 3,
                },
                "rail_type": {
                    "type": "integer",
                    "description": "Rail type ID for dry-run test. Default 0.",
                    "default": 0,
                },
                "required_cargo": {
                    "type": "string",
                    "description": "Only return spots where this cargo is produced (e.g. 'COAL', 'IORE').",
                },
            },
            "required": ["tile"],
        },
        "gs_action": "find_flat_spots",
        "inject_company_id": True,
    },
    {
        "name": "find_station_spot",
        "description": (
            "Find validated rail station spots near an industry or town."
            " Combines flat-land check, station dry-run, and cargo catchment validation."
            " For industries: returns spots where the industry's cargo is produced/accepted."
            " For towns: returns spots where passengers or mail are available."
            " Provide either industry_id OR town_id (not both)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "industry_id": {
                    "type": "integer",
                    "description": "Industry ID (for cargo routes). From get_industries or route_planning.",
                },
                "town_id": {
                    "type": "integer",
                    "description": "Town ID (for passenger/mail routes). From get_towns or route_planning.",
                },
                "platform_length": {
                    "type": "integer",
                    "description": "Station platform length. Default 3.",
                    "default": 3,
                },
                "rail_type": {
                    "type": "integer",
                    "description": "Rail type ID. Default 0.",
                    "default": 0,
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius. Default 15.",
                    "default": 15,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max spots to return. Default 5.",
                    "default": 5,
                },
            },
            "required": [],
        },
        "gs_action": "find_station_spot",
        "inject_company_id": True,
    },
    {
        "name": "find_water_depot_spots",
        "description": (
            "Find water tiles where a ship depot can be built (dry-run validated)."
            " Returns tile, x, y for each spot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "town_id": {"type": "integer", "description": "Town to search near."},
                "tile": {"type": "integer", "description": "Center tile to search near (alternative to town_id)."},
                "max_results": {"type": "integer", "description": "Max spots to return.", "default": 5},
            },
            "required": [],
        },
        "gs_action": "find_water_depot_spots",
        "inject_company_id": True,
    },
    {
        "name": "get_hangars",
        "description": (
            "List airport hangars (depot tiles) for your company."
            " Returns hangar_tile for use as depot_tile in buy_vehicle."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "gs_action": "get_hangars",
        "inject_company_id": True,
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
    {
        "name": "pathfind",
        "description": (
            "Find an optimal path between two map coordinates."
            " Returns a list of path steps including bridges and tunnels."
            " Use the result with build_path action to build the infrastructure."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_x": {"type": "integer", "description": "Start x coordinate."},
                "from_y": {"type": "integer", "description": "Start y coordinate."},
                "to_x": {"type": "integer", "description": "End x coordinate."},
                "to_y": {"type": "integer", "description": "End y coordinate."},
                "transport_type": {
                    "type": "string",
                    "description": "Transport type: road, rail, or water.",
                    "enum": ["road", "rail", "water"],
                },
            },
            "required": ["from_x", "from_y", "to_x", "to_y", "transport_type"],
        },
        "custom_handler": "pathfind",
    },
]


class ObservationToolkit:
    """Provides observation tools for a gameloop agent.

    Tools are read-only GS queries that agents can call during the
    decide phase to gather information before choosing actions.
    Results are filtered by agent_type so each agent only sees its
    own vehicle and station types.

    The ``pathfind`` tool is handled specially: it runs the Python A*
    pathfinder instead of going through the GS bridge.
    """

    def __init__(
        self,
        admin_client: AdminClient,
        company_id: int,
        agent_type: str = "general",
        map_width: int = 0,
        map_height: int = 0,
    ) -> None:
        self._client = admin_client
        self._company_id = company_id
        self._agent_type = agent_type
        self._map_width = map_width
        self._map_height = map_height
        self._vehicle_types = AGENT_VEHICLE_TYPES.get(agent_type, AGENT_VEHICLE_TYPES["general"])
        self._station_filter = AGENT_STATION_FILTERS.get(agent_type, AGENT_STATION_FILTERS["general"])
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

        # Custom handlers bypass the GS bridge
        custom = tool_def.get("custom_handler")
        if custom == "pathfind":
            return await self._handle_pathfind(arguments)

        gs_action = tool_def["gs_action"]
        params = dict(arguments)

        # Inject company_id for tools that need it
        if tool_def.get("inject_company_id") and "company_id" not in params:
            params["company_id"] = self._company_id

        try:
            result = await self._client.send_gamescript(gs_action, params, timeout=15.0)
            if result.get("success"):
                data = result.get("result", {})
                data = self._filter_by_agent_type(tool_name, data)
                return json.dumps(data, indent=2)
            return json.dumps({"error": result.get("error", "GS query failed")})
        except Exception as exc:
            logger.warning("Tool %s execution failed: %s", tool_name, exc)
            return json.dumps({"error": str(exc)})

    async def _handle_pathfind(self, arguments: dict[str, Any]) -> str:
        """Run the Python A* pathfinder and return the result."""
        from nttd.pathfinding import service as pf_service

        if pf_service.get_cache() is None:
            if self._map_width > 0 and self._map_height > 0:
                pf_service.init_cache(self._map_width, self._map_height)
            else:
                return json.dumps({"error": "Map dimensions not available yet"})

        try:
            result = await pf_service.pathfind(
                from_x=arguments["from_x"],
                from_y=arguments["from_y"],
                to_x=arguments["to_x"],
                to_y=arguments["to_y"],
                transport_type=arguments["transport_type"],
                gs_client=self._client,
                company_id=self._company_id,
            )
            return json.dumps(result)
        except Exception as exc:
            logger.warning("Pathfind tool failed: %s", exc)
            return json.dumps({"error": str(exc)})

    def _filter_by_agent_type(self, tool_name: str, data: Any) -> Any:
        """Filter tool results so agents only see their own vehicle/station types."""
        if not isinstance(data, list):
            return data
        if tool_name == "get_vehicles":
            return [v for v in data if v.get("type") in self._vehicle_types]
        if tool_name == "get_stations":
            return [s for s in data if self._station_filter(s)]
        return data
