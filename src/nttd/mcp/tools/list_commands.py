"""``list_commands``: what each command and query takes, from the manifest."""

from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp.game_session import AGENT_TAG_PARAM, GameSession

LIST_COMMANDS_NAME_PARAM = "A command or query name. Empty lists all of them."

LIST_COMMANDS = """Describe a command or query: its parameters, their types,
defaults, and the exact values they accept.
"""


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the manifest tool. It needs no running game."""

    @mcp.tool(description=LIST_COMMANDS)
    async def list_commands(
        name: Annotated[str | None, Field(description=LIST_COMMANDS_NAME_PARAM)] = None,
        agent_tag: Annotated[str | None, Field(description=AGENT_TAG_PARAM)] = None,
    ) -> str:
        return json.dumps(session.lookup_action(name or None))
