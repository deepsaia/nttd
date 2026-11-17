"""``focus``: choose the part of the map an agent's replies describe."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp import texts
from nttd.mcp.focus import DEFAULT_PADDING
from nttd.mcp.game_session import GameSession
from nttd.mcp.moves import coerce_flag

FOCUS_KEYS = ("towns", "industries", "x1", "y1", "x2", "y2", "padding")


async def run_focus(session: GameSession, tag: str, args: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """What one focus call does, shared with the round envelope."""
    if coerce_flag(args.get("clear")):
        return await session.clear_focus(tag, snapshot)
    return await session.set_focus(tag, {key: args.get(key) for key in FOCUS_KEYS}, snapshot)


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the focus tool."""

    @mcp.tool(description=texts.FOCUS)
    async def focus(
        towns: Annotated[list[str] | None, Field(description=texts.FOCUS_TOWNS_PARAM)] = None,
        industries: Annotated[list[str] | None, Field(description=texts.FOCUS_INDUSTRIES_PARAM)] = None,
        x1: Annotated[int | None, Field(description=texts.FOCUS_X1_PARAM)] = None,
        y1: Annotated[int | None, Field(description=texts.FOCUS_Y1_PARAM)] = None,
        x2: Annotated[int | None, Field(description=texts.FOCUS_X2_PARAM)] = None,
        y2: Annotated[int | None, Field(description=texts.FOCUS_Y2_PARAM)] = None,
        padding: Annotated[int, Field(description=texts.FOCUS_PADDING_PARAM.format(default_padding=DEFAULT_PADDING))] = DEFAULT_PADDING,
        clear: Annotated[bool, Field(description=texts.FOCUS_CLEAR_PARAM)] = False,
        agent_tag: Annotated[str | None, Field(description=texts.AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        args = {"towns": towns, "industries": industries, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "padding": padding, "clear": clear}
        return json.dumps(await run_focus(session, session.tag(agent_tag), args))
