"""``nttd_observe``: the whole world, as one call."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from nttd.mcp.participant_client import ParticipantClient


def register(mcp: FastMCP, client: ParticipantClient) -> None:
    """Register the observation tool."""

    @mcp.tool()
    async def nttd_observe() -> str:
        """Read the whole game state: your company, the map, towns, industries,
        stations, vehicles, and the rest of the world.

        This returns everything rather than a summary. Deciding what matters is the
        task, so nttd does not do that part for you. Filter it in your own code.

        For anything not in the snapshot, such as which tiles are buildable or what a
        move would cost, use nttd_query.
        """
        return json.dumps(await client.observe())
