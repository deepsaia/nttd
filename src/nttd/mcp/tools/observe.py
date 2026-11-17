"""``observe``: the game state, as one agent sees it."""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp import texts
from nttd.mcp.game_session import GameSession


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the observation tool."""

    @mcp.tool(description=texts.OBSERVE)
    async def observe(
        agent_tag: Annotated[str | None, Field(description=texts.AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(await session.observe(session.tag(agent_tag)))
