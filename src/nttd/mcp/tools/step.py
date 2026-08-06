"""``nttd_step``: act and advance the world, in one call."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from nttd.mcp.participant_client import ParticipantClient
from nttd.mcp.tools.act import Move


def register(mcp: FastMCP, client: ParticipantClient) -> None:
    """Register the stepping tool."""

    @mcp.tool()
    async def nttd_step(moves: list[Move] | None = None, days: int | None = None) -> str:
        """Submit actions, advance the game, and return the world afterwards.

        For a stepped session. The call does not return until the world has moved and
        been observed again, so you never have to guess when your actions took effect
        or how long to wait.

        Send as many actions as you like. There is no per-step limit: a stepped run is
        bounded by how many steps it takes and how many game-days each advances, both
        fixed by the scenario, so a bigger batch buys you no more world than anyone
        else gets. Deliberating between steps is free, which is the point of stepping.

        Leave days unset. It overrides the scenario's step size, exists for
        experimentation, and is ignored in a scored run where the step size is part of
        the task.
        """
        payload = [
            {"action": move.action_type.value, "params": move.parameters}
            for move in (moves or [])
        ]
        return json.dumps(await client.step(payload, days))
