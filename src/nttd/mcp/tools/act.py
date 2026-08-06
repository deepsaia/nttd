"""``nttd_act``: submit moves, in real time."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from nttd.mcp.action_types import PlayableAction
from nttd.mcp.participant_client import ParticipantClient


class Move(BaseModel):
    """One action and its parameters.

    ``action_type`` is an enum rather than a string, so every name a contestant may
    submit arrives in the tool schema and a client never has to be told them in a
    prompt. Parameters stay an open object because they differ per action: what each
    one takes is in nttd_actions.
    """

    action_type: PlayableAction = Field(description="Which action to run.")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Its parameters. See nttd_actions.",
    )


def register(mcp: FastMCP, client: ParticipantClient) -> None:
    """Register the action tool."""

    @mcp.tool()
    async def nttd_act(moves: list[Move], dry_run: bool = False) -> str:
        """Submit one or more actions to the game, in order.

        Use this in a real-time session. In a stepped session use nttd_step, which
        submits and advances in one call.

        There is no limit on how many you may send. Each is attempted in order, and
        the reply reports each one separately: a refusal is normal play, not an error,
        and the usual reasons are money, a tile that will not take the structure, or a
        town that thinks poorly of you.

        With dry_run the actions are only checked, and nothing is submitted. Worth
        doing for a batch you are unsure of, since a refused action still costs a round
        trip.

        The company is taken from this server's participant token. You cannot act for
        another company, and you do not pass a company id.
        """
        payload = [
            {"action_type": move.action_type.value, "parameters": move.parameters}
            for move in moves
        ]
        if dry_run:
            return json.dumps({"dry_run": True, **await client.validate(payload)})

        results = [
            await client.submit(entry["action_type"], entry["parameters"])
            for entry in payload
        ]
        return json.dumps({"submitted": len(results), "results": results})
