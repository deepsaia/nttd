"""``query``: ask the game something the state does not carry."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp import texts
from nttd.mcp.action_types import ObservationAction
from nttd.mcp.game_session import GameSession
from nttd.mcp.moves import coerce_params


async def run_query(session: GameSession, name: Any, raw_parameters: Any) -> dict[str, Any]:
    """What one query call does, shared with the round envelope."""
    parameters = coerce_params(raw_parameters)
    if parameters is None:
        return {"error": texts.PARAMETERS_FORMAT_HINT}
    return await session.query(str(getattr(name, "value", name)), parameters)


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the query tool. Its text names every query."""
    description = texts.query_description([member.value for member in ObservationAction])

    @mcp.tool(description=description)
    async def query(
        query: Annotated[ObservationAction, Field(description=texts.QUERY_QUERY_PARAM)],
        parameters: Annotated[dict[str, Any] | None, Field(description=texts.QUERY_PARAMETERS_PARAM)] = None,
        agent_tag: Annotated[str | None, Field(description=texts.AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(await run_query(session, query, parameters))
