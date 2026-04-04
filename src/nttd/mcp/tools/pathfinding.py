"""Pathfinding tools — find routes between map coordinates."""

import json

from mcp.server.fastmcp import FastMCP

from nttd.mcp.client import NttdMCPClient


def register_pathfinding_tools(mcp: FastMCP, client: NttdMCPClient) -> None:
    """Register pathfinding tools on the MCP server."""

    @mcp.tool()
    async def pathfind(
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        transport_type: str = "road",
        avoid_demolish: bool = False,
    ) -> str:
        """Find a path between two map coordinates.

        Returns a list of tiles forming the shortest path for the given transport type.

        Args:
            from_x: Starting X coordinate.
            from_y: Starting Y coordinate.
            to_x: Destination X coordinate.
            to_y: Destination Y coordinate.
            transport_type: Transport mode — "road", "rail", or "water".
            avoid_demolish: If True, avoid paths that require demolishing structures.
        """
        result = await client.pathfind(
            from_x=from_x,
            from_y=from_y,
            to_x=to_x,
            to_y=to_y,
            transport_type=transport_type,
            avoid_demolish=avoid_demolish,
        )
        return json.dumps(result, indent=2)
