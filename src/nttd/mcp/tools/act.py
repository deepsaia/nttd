"""``act``: send game commands, in every game mode."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from nttd.config import action_manifest
from nttd.mcp import texts
from nttd.mcp.action_types import PlayableAction
from nttd.mcp.game_session import GameSession
from nttd.mcp.moves import coerce_flag, read_moves


class Move(BaseModel):
    """One game command and its parameters.

    ``command`` is an enum, so every name an agent may send arrives in the tool schema
    and a name outside the manifest cannot be sent at all.
    """

    command: PlayableAction = Field(description=texts.MOVE_COMMAND_PARAM)
    parameters: dict[str, Any] = Field(default_factory=dict, description=texts.MOVE_PARAMETERS_PARAM)


async def run_act(session: GameSession, tag: str, raw_moves: Any, dry_run: Any) -> dict[str, Any]:
    """What one act call does, shared with the round envelope."""
    moves, error = read_moves(raw_moves)
    if error:
        return {"error": error}
    if coerce_flag(dry_run):
        return await session.validate(moves)
    results = await session.play_round({tag: moves})
    return session.view(tag, results[tag])


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the action tool. Its text names the commands by group for the mode."""
    description = texts.act_description(
        session.mode, action_manifest.manifest(), [member.value for member in PlayableAction],
    )

    @mcp.tool(description=description)
    async def act(
        moves: Annotated[list[Move] | None, Field(description=texts.ACT_MOVES_PARAM)] = None,
        dry_run: Annotated[bool, Field(description=texts.ACT_DRY_RUN_PARAM)] = False,
        agent_tag: Annotated[str | None, Field(description=texts.AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(await run_act(session, session.tag(agent_tag), moves or [], dry_run))
