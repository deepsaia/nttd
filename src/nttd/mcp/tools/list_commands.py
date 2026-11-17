"""``list_commands``: what each command and query takes, from the manifest."""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp import texts
from nttd.mcp.game_session import GameSession


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the manifest tool. It needs no running game."""

    @mcp.tool(description=texts.LIST_COMMANDS)
    async def list_commands(
        name: Annotated[str | None, Field(description=texts.LIST_COMMANDS_NAME_PARAM)] = None,
        agent_tag: Annotated[str | None, Field(description=texts.AGENT_TAG_PARAM)] = None,
    ) -> str:
        return json.dumps(session.lookup_action(name or None))
