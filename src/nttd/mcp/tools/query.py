"""``query``: ask the game something the state does not carry."""

from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from nttd.mcp.action_types import ObservationAction
from nttd.mcp.game_session import AGENT_TAG_PARAM, GameSession
from nttd.mcp.moves import coerce_params

PARAMETERS_FORMAT_HINT = 'parameters must be an object, e.g. {"town_id": 3}.'

QUERY_QUERY_PARAM = "Name of the query."

QUERY_PARAMETERS_PARAM = "The query's parameters."

QUERY_BODY = """Queries return information about the world at the moment they run.
They are executed and return information before the commands.

Examples include whether a tile is buildable, where a station fits, which engines are for sale this
year, a town's rating, etc...
To see query parameters use the list_commands tool.
"""


async def run_query(
    session: GameSession, name: Any, raw_parameters: Any
) -> dict[str, Any]:
    """What one query call does, shared with the round envelope."""
    parameters = coerce_params(raw_parameters)
    if parameters is None:
        return {"error": PARAMETERS_FORMAT_HINT}
    return await session.query(str(getattr(name, "value", name)), parameters)


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the query tool. The query names arrive in its schema."""

    @mcp.tool(description=QUERY_BODY)
    async def query(
        query: Annotated[ObservationAction, Field(description=QUERY_QUERY_PARAM)],
        parameters: Annotated[
            dict[str, Any] | None, Field(description=QUERY_PARAMETERS_PARAM)
        ] = None,
        agent_tag: Annotated[str | None, Field(description=AGENT_TAG_PARAM)] = None,
    ) -> str:
        await session.ensure_started()
        return json.dumps(await run_query(session, query, parameters))
