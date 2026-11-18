"""``act``: send game commands, in every game mode."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from nttd.mcp.action_types import PlayableAction
from nttd.mcp.game_session import AGENT_TAG_PARAM, GameSession
from nttd.mcp.moves import coerce_flag, read_moves

ACT_TIMING_STEPPED = """Each time you call this tool the game advances a day.
An empty list sends no commands, but still advances the day."""

ACT_TIMING_CLOCKED = """An empty list sends no commands."""

ACT_BODY = """Send game commands to the company.
Commands are listed in the "moves" field and executed in the given order.
{timing}

The reply reports each command's outcome and any created IDs in changed_entities.
A refused command is normal play and can happen for many in-game reasons.

Examples of command formatting:
  no command:   {{"moves": []}}
  one command:      {{"moves": [{{"command": "command_name", "parameters": {{"key": value}}}}]}}
  several commands: {{"moves": [{{"command": "command_name", "parameters": {{"key": value}}}},
                               {{"command": "command_name", "parameters": {{"key": value}}}}]}}

With a focus set, the snapshot in the reply covers only the focus; the
command outcomes are always complete.

Use list_commands(name=...) for parameter names, types and required alternatives.
Unknown fields and wrong types are rejected.
"""


# One game command and its parameters. No docstring and no field descriptions: the
# schema builder sends them to the agent, and the act description already explains the
# shape. ``command`` is an enum, so every name an agent may send arrives in the tool
# schema and a name outside the manifest cannot be sent at all.
class Move(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: PlayableAction
    parameters: dict[str, Any] = Field(default_factory=dict)


async def run_act(
    session: GameSession, tag: str, raw_moves: Any, dry_run: Any
) -> dict[str, Any]:
    """What one act call does, shared with the round envelope."""
    moves, error = read_moves(raw_moves)
    if error:
        return {"error": error}
    if coerce_flag(dry_run):
        return await session.validate(moves)
    results = await session.play_round({tag: moves})
    return session.view(tag, results[tag])


def register(mcp: FastMCP, session: GameSession) -> None:
    if session.mode == "stepped":
        timing = ACT_TIMING_STEPPED
    else:
        timing = ACT_TIMING_CLOCKED
    description = ACT_BODY.format(timing=timing)

    @mcp.tool(description=description)
    async def act(
        moves: list[Move] | None = None,
        dry_run: Annotated[
            bool,
            Field(
                description="If True, only check the commands formatting, without sending them."
            ),
        ] = False,
        agent_tag: Annotated[str | None, Field(description=AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(
            await run_act(session, session.tag(agent_tag), moves or [], dry_run)
        )
