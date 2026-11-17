"""``observe``: the game state, as one agent sees it."""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp.game_session import AGENT_TAG_PARAM, GameSession

OBSERVE = """Read the game state: the company, towns, industries, stations,
vehicles, routes, and the rest of the world.

The reply is the full state.
With a focus set, the map part covers only the focus.
To see which tiles are buildable or how much a game command costs, use the query tool.
"""


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the observation tool."""

    @mcp.tool(description=OBSERVE)
    async def observe(
        agent_tag: Annotated[str | None, Field(description=AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(await session.observe(session.tag(agent_tag)))
