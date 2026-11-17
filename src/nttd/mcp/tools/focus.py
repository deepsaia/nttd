"""``focus``: choose the part of the map an agent's replies describe."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp.focus import DEFAULT_PADDING
from nttd.mcp.game_session import AGENT_TAG_PARAM, GameSession
from nttd.mcp.moves import coerce_flag

FOCUS_TOWNS_PARAM = "Town names or ids to include."

FOCUS_INDUSTRIES_PARAM = "Industry names or ids to include."

FOCUS_X1_PARAM = "Left tile column of a rectangle to include."

FOCUS_Y1_PARAM = "Top tile row of a rectangle to include."

FOCUS_X2_PARAM = "Right tile column of a rectangle to include."

FOCUS_Y2_PARAM = "Bottom tile row of a rectangle to include."

FOCUS_PADDING_PARAM = "Tiles added on each side of the named places. Default {default_padding}."

FOCUS_CLEAR_PARAM = "True removes the focus."

FOCUS = """Choose the part of the map that your game replies describe.

Name towns or industries, by name or id, or give a tile rectangle
x1, y1, x2, y2, or both. The focus is the rectangle around them,
widened by padding tiles on each side. From then on, replies from
observe and act list only what is inside the focu. 
The company, the date and the outcomes of your own commands stay complete.
Each reply also carries an outside section, the towns and industries
outside with their coordinates and the counts of everything left out,
and the names of the agents whose focus overlaps yours. Agents without
a focus see the whole map.

Examples of params:
  two places:   {"towns": ["<town name>"], "industries": ["<industry name>"]}
  a rectangle:  {"x1": 100, "y1": 20, "x2": 160, "y2": 80}
  remove it:    {"clear": true}

The reply is the game state seen through the new focus.
"""


FOCUS_KEYS = ("towns", "industries", "x1", "y1", "x2", "y2", "padding")


async def run_focus(session: GameSession, tag: str, args: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """What one focus call does, shared with the round envelope."""
    if coerce_flag(args.get("clear")):
        return await session.clear_focus(tag, snapshot)
    return await session.set_focus(tag, {key: args.get(key) for key in FOCUS_KEYS}, snapshot)


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the focus tool."""

    @mcp.tool(description=FOCUS)
    async def focus(
        towns: Annotated[list[str] | None, Field(description=FOCUS_TOWNS_PARAM)] = None,
        industries: Annotated[list[str] | None, Field(description=FOCUS_INDUSTRIES_PARAM)] = None,
        x1: Annotated[int | None, Field(description=FOCUS_X1_PARAM)] = None,
        y1: Annotated[int | None, Field(description=FOCUS_Y1_PARAM)] = None,
        x2: Annotated[int | None, Field(description=FOCUS_X2_PARAM)] = None,
        y2: Annotated[int | None, Field(description=FOCUS_Y2_PARAM)] = None,
        padding: Annotated[int, Field(description=FOCUS_PADDING_PARAM.format(default_padding=DEFAULT_PADDING))] = DEFAULT_PADDING,
        clear: Annotated[bool, Field(description=FOCUS_CLEAR_PARAM)] = False,
        agent_tag: Annotated[str | None, Field(description=AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        args = {"towns": towns, "industries": industries, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "padding": padding, "clear": clear}
        return json.dumps(await run_focus(session, session.tag(agent_tag), args))
