"""``nttd_query``: ask the game something the snapshot does not carry."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from nttd.mcp.action_types import ObservationAction
from nttd.mcp.participant_client import ParticipantClient


def register(mcp: FastMCP, client: ParticipantClient) -> None:
    """Register the query tool."""

    @mcp.tool()
    async def nttd_query(
        query: ObservationAction, parameters: dict[str, Any] | None = None,
    ) -> str:
        """Ask the running game a question. Costs nothing and changes nothing.

        The world snapshot from nttd_observe does not carry everything. These are the
        live reads: whether a tile is buildable, where a station would fit, which
        engines can be bought this year, what an action would cost before you commit to
        it.

        Worth knowing which ones matter most:

          find_flat_spots, find_station_spot   where something will actually fit
          get_engines, get_engine_details      what is buyable now, which changes by year
          estimate_cost                        what a move costs, without making it
          get_tile_info, get_tile_area         the ground itself
          get_town_rating                      whether a town will let you build

        One is not free of consequence despite being a read: get_cargo_flows resets the
        cargo monitors, so a second call reports only what moved since the first.

        Parameters differ per query. nttd_actions gives them.
        """
        return json.dumps(await client.query(query.value, parameters or {}))
