"""Observation tools — read game state without modifying it."""

import json

from mcp.server.fastmcp import FastMCP

from nttd.mcp.client import NttdMCPClient


def register_observation_tools(mcp: FastMCP, client: NttdMCPClient) -> None:
    """Register all observation/query tools on the MCP server."""

    @mcp.tool()
    async def get_state_compact() -> str:
        """Get a compact, LLM-friendly summary of the current game state.

        Returns: company finances, vehicle counts, top stations, top towns,
        active routes, subsidies, and recent actions (~1-3 KB).
        """
        result = await client.observe_compact()
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_state_full() -> str:
        """Get the full game state snapshot with all entities.

        Returns: all companies, towns, industries, stations, vehicles, routes,
        subsidies (~15-50 KB). Use get_state_compact for a smaller summary.
        """
        result = await client.observe_full()
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_session_status() -> str:
        """Get current session status: game date, paused state, mode, speed, map dimensions."""
        result = await client.get_session_status()
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_companies() -> str:
        """List all active companies. Returns: id, name, is_ai, color, manager for each."""
        result = await client.gs_query("get_companies")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_company_finance(company_id: int | None = None) -> str:
        """Get financial details for a company: balance, loan, income, value, profit.

        Args:
            company_id: Company to query. Defaults to your company.
        """
        cid = company_id if company_id is not None else client.company_id
        result = await client.gs_query("get_company_finance", {"company_id": cid})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_towns() -> str:
        """List all towns on the map: id, name, population, x, y, is_city."""
        result = await client.gs_query("get_towns")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_town_info(town_id: int) -> str:
        """Get detailed info about a specific town.

        Args:
            town_id: The town ID to query.
        """
        result = await client.gs_query("get_town_info", {"town_id": town_id})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_industries() -> str:
        """List all industries: id, name, type, location, production, acceptance."""
        result = await client.gs_query("get_industries")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_industry_info(industry_id: int) -> str:
        """Get detailed info about a specific industry.

        Args:
            industry_id: The industry ID to query.
        """
        result = await client.gs_query("get_industry_info", {"industry_id": industry_id})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_stations(company_id: int | None = None) -> str:
        """List stations owned by a company: id, name, location, cargo waiting.

        Args:
            company_id: Company to query. Defaults to your company.
        """
        cid = company_id if company_id is not None else client.company_id
        result = await client.gs_query("get_stations", {"company_id": cid})
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_station_info(station_id: int) -> str:
        """Get detailed info about a specific station.

        Args:
            station_id: The station ID to query.
        """
        result = await client.gs_query("get_station_info", {"station_id": station_id})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_vehicles(company_id: int | None = None) -> str:
        """List vehicles owned by a company: id, type, name, profit, depot status.

        Args:
            company_id: Company to query. Defaults to your company.
        """
        cid = company_id if company_id is not None else client.company_id
        result = await client.gs_query("get_vehicles", {"company_id": cid})
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_vehicle_info(vehicle_id: int) -> str:
        """Get detailed info about a specific vehicle.

        Args:
            vehicle_id: The vehicle ID to query.
        """
        result = await client.gs_query("get_vehicle_info", {"vehicle_id": vehicle_id})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_engines(vehicle_type: int = 1, company_id: int | None = None) -> str:
        """List purchasable engine types.

        Args:
            vehicle_type: 0=train, 1=road vehicle, 2=ship, 3=aircraft.
            company_id: Company context. Defaults to your company.
        """
        cid = company_id if company_id is not None else client.company_id
        result = await client.gs_query("get_engines", {"company_id": cid, "vehicle_type": vehicle_type})
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_cargo_types() -> str:
        """List all cargo types in the game: id, label, name."""
        result = await client.gs_query("get_cargo_types")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_subsidies() -> str:
        """List active subsidies: cargo, source, destination, value, remaining years."""
        result = await client.gs_query("get_subsidies")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_tile_info(tile: int) -> str:
        """Get terrain and infrastructure details for a map tile.

        Args:
            tile: Tile ID (calculated as y * map_width + x).
        """
        result = await client.gs_query("get_tile_info", {"tile": tile})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_map_size() -> str:
        """Get the map dimensions."""
        result = await client.gs_query("get_map_size")
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def get_date() -> str:
        """Get the current in-game date."""
        result = await client.gs_query("get_date")
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def scan_town_area(town_id: int) -> str:
        """Scan the area around a town for buildable tiles.

        Args:
            town_id: Town to scan around.
        """
        result = await client.gs_query("scan_town_area", {"town_id": town_id})
        return json.dumps(result.get("result", {}), indent=2)

    @mcp.tool()
    async def find_bus_stop_spots(town_id: int, max_results: int = 5) -> str:
        """Find road tiles near a town suitable for bus/truck stops.

        Args:
            town_id: Town to search near.
            max_results: Maximum number of spots to return.
        """
        result = await client.gs_query("find_bus_stop_spots", {
            "town_id": town_id, "company_id": client.company_id, "max_results": max_results,
        })
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def find_depot_spots(town_id: int, max_results: int = 5) -> str:
        """Find road tiles near a town suitable for a road depot.

        Args:
            town_id: Town to search near.
            max_results: Maximum number of spots to return.
        """
        result = await client.gs_query("find_depot_spots", {
            "town_id": town_id, "company_id": client.company_id, "max_results": max_results,
        })
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_orders(vehicle_id: int) -> str:
        """Get the order list for a vehicle.

        Args:
            vehicle_id: Vehicle to query orders for.
        """
        result = await client.gs_query("get_orders", {"vehicle_id": vehicle_id})
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_rail_types() -> str:
        """List available rail types."""
        result = await client.gs_query("get_rail_types")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_road_types() -> str:
        """List available road types."""
        result = await client.gs_query("get_road_types")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_bridge_types() -> str:
        """List available bridge types with speed limits and costs."""
        result = await client.gs_query("get_bridge_types")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_airport_types() -> str:
        """List available airport types with dimensions and capacities."""
        result = await client.gs_query("get_airport_types")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_groups(company_id: int | None = None) -> str:
        """List vehicle groups for a company.

        Args:
            company_id: Company to query. Defaults to your company.
        """
        cid = company_id if company_id is not None else client.company_id
        result = await client.gs_query("get_groups", {"company_id": cid})
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_signs() -> str:
        """List all signs on the map."""
        result = await client.gs_query("get_signs")
        return json.dumps(result.get("result", []), indent=2)

    @mcp.tool()
    async def get_town_rating(town_id: int, company_id: int | None = None) -> str:
        """Get the local authority rating for a company in a town.

        Args:
            town_id: Town to check rating in.
            company_id: Company to check. Defaults to your company.
        """
        cid = company_id if company_id is not None else client.company_id
        result = await client.gs_query("get_town_rating", {"town_id": town_id, "company_id": cid})
        return json.dumps(result.get("result", {}), indent=2)
