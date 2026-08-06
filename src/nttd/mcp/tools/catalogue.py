"""``nttd_actions``: what each action takes, on demand."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from nttd.config import action_manifest


def register(mcp: FastMCP) -> None:
    """Register the manifest tool.

    Takes no client: the manifest describes the build rather than a session, so this
    answers whether or not a game is running.
    """

    @mcp.tool()
    async def nttd_actions(action_type: str | None = None) -> str:
        """Look up what an action takes: parameters, types, defaults, and the exact
        values any of them accept.

        Call this before composing an action you have not used. The names themselves
        are already in the nttd_act and nttd_query schemas, so this is for the
        parameters, and there are three things about them worth reading rather than
        guessing:

          Some take named constants, and the numbers are not guessable. order_flags is
          a bitmask you add together where OF_FULL_LOAD is 64 and OF_NO_LOAD is 128,
          and OF_UNLOAD and OF_SERVICE_IF_NEEDED are both 4.

          Some actions accept a choice. add_order takes a station id or a destination
          tile; anything placed on the map takes tile or an x,y pair. The one_of field
          says which.

          Some ids are assigned by the running game and gated by year: rail types, road
          types, cargo types, bridge types, engines. Ask for them with nttd_query
          rather than reusing a number that worked before.

        Without an action_type this returns one line per action, which is smaller than
        the full manifest and enough to choose from.
        """
        if action_type is None:
            summary = {
                name: entry["description"].split(". ")[0]
                for name, entry in sorted(action_manifest.ACTIONS.items())
                if entry["tier"] != "operator"
            }
            return json.dumps({"count": len(summary), "actions": summary})

        entry = action_manifest.ACTIONS.get(action_type)
        if entry is None:
            import difflib  # noqa: PLC0415

            return json.dumps({
                "error": f"No such action: {action_type}",
                "did_you_mean": difflib.get_close_matches(
                    action_type, action_manifest.ACTIONS, n=5, cutoff=0.5,
                ),
            })
        return json.dumps({"action_type": action_type, **entry})
