"""``act``: send game commands, in every game mode."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from nttd.config import action_manifest
from nttd.mcp.action_types import PlayableAction
from nttd.mcp.game_session import AGENT_TAG_PARAM, GameSession
from nttd.mcp.moves import coerce_flag, read_moves

MOVE_COMMAND_PARAM = "Which game command to run."

MOVE_PARAMETERS_PARAM = "Its parameters. See the list_commands tool."

ACT_MOVES_PARAM = "Game commands, each with a command name and its parameters. They run in the specified order."

ACT_DRY_RUN_PARAM = "Only check the commands. Nothing is sent, the day does not advance, and you do not count as a submitter."

ACT_OPENING_STEPPED = "Send game commands to the company, or pass the day without any."

ACT_TIMING_STEPPED = """The commands of all agents in this turn form one batch. The batch runs
the agents in a random order, and the game advances one day after it. An empty moves list sends no command;
the day still advances and you count as a submitter."""

ACT_EMPTY_EXAMPLE_STEPPED = "pass the day:  "

ACT_OPENING_CLOCKED = "Send game commands to the company."

ACT_TIMING_CLOCKED = """The game runs on its own clock. Your commands run as soon as they
arrive, in the order given; the commands of other agents run when theirs
arrive. An empty moves list sends no command; you still count as a submitter."""

ACT_EMPTY_EXAMPLE_CLOCKED = "no command:    "

ACT_BODY = """{opening}
This single turn action can carry several commands: the moves list
holds them, and they run in the order given.

{timing} The reply reports
the outcome of each of your commands. A refused command is normal play
and can happen for many in-game reasons.

With dry_run true the commands are only checked for their names and
parameters. Nothing is sent, the day does not advance, and you do not
count as a submitter.

Examples of command formatting:
  {empty_example}   {{"moves": []}}
  one command:      {{"moves": [{{"command": "command_name", "parameters": {{"key": value}}}}]}}
  several commands: {{"moves": [{{"command": "command_name", "parameters": {{"key": value, "another_key": another_value}}}},
                               {{"command": "command_name", "parameters": {{"key": value, "another_key": another_value}}}}]}}

With a focus set, the snapshot in the reply covers only the focus; the
command outcomes are always complete.

Available game commands, by group. The list_commands tool gives the parameters of each:
{commands_by_group}
"""

def commands_by_group(manifest: dict, names: list[str]) -> str:
    """One line per manifest category, listing the given command names."""
    groups: dict[str, list[str]] = {}
    for name in names:
        category = manifest.get("actions", {}).get(name, {}).get("category", "other")
        groups.setdefault(category, []).append(name)
    return "\n".join(
        f"  {category}: {', '.join(sorted(members))}"
        for category, members in sorted(groups.items())
    )

def act_description(mode: str, manifest: dict, commands: list[str]) -> str:
    """The act tool text for the session's mode."""
    if mode == "stepped":
        opening, timing, example = ACT_OPENING_STEPPED, ACT_TIMING_STEPPED, ACT_EMPTY_EXAMPLE_STEPPED
    else:
        opening, timing, example = ACT_OPENING_CLOCKED, ACT_TIMING_CLOCKED, ACT_EMPTY_EXAMPLE_CLOCKED
    return ACT_BODY.format(
        opening=opening, timing=timing, empty_example=example,
        commands_by_group=commands_by_group(manifest, commands),
    )



class Move(BaseModel):
    """One game command and its parameters.

    ``command`` is an enum, so every name an agent may send arrives in the tool schema
    and a name outside the manifest cannot be sent at all.
    """

    command: PlayableAction = Field(description=MOVE_COMMAND_PARAM)
    parameters: dict[str, Any] = Field(default_factory=dict, description=MOVE_PARAMETERS_PARAM)


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
    description = act_description(
        session.mode, action_manifest.manifest(), [member.value for member in PlayableAction],
    )

    @mcp.tool(description=description)
    async def act(
        moves: Annotated[list[Move] | None, Field(description=ACT_MOVES_PARAM)] = None,
        dry_run: Annotated[bool, Field(description=ACT_DRY_RUN_PARAM)] = False,
        agent_tag: Annotated[str | None, Field(description=AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(await run_act(session, session.tag(agent_tag), moves or [], dry_run))
