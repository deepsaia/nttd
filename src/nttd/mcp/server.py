"""The nttd MCP server: five tools that are enough to play a whole game.

    uv run python -m nttd.mcp.server --session ses_abc --token <participant-token>
    uv run python -m nttd.mcp.server --session ses_abc --token <tok> --transport http

What this replaces was not a play surface. It had 33 tools, 30 of them getters wrapping
one REST call each, and no way to act or step at all: its own docstring said execution
happened somewhere else. An agent connected to it could look at the game and do nothing.

Five, because the tools are the verbs and there are only five:

    nttd_observe   read the world
    nttd_act       change it, in real time
    nttd_step      change it and advance, for stepped play
    nttd_query     ask something the snapshot does not carry
    nttd_actions   look up what an action takes

The 120 actions are not hidden by this. ``action_type`` is an enum, so every name is in
the tool schema where a client already looks, and 30 near-identical getters were never
the vocabulary anyway: they were one wrapper per endpoint, which is a shape that grows
with the API rather than with the game.

Both transports are supported because both kinds of client matter here: stdio for an
agent that launches the server as a subprocess, and streamable HTTP for a multi-agent
framework that connects to one already running.

One server is one seat. It holds a single session and a single participant token, so no
tool takes a session argument and no client can act for a company it was not given.
"""

from __future__ import annotations

import argparse
import logging
import os

from mcp.server.fastmcp import FastMCP

from nttd.mcp.participant_client import ParticipantClient
from nttd.mcp.tools import act, catalogue, observe, query, step

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8000"

_INSTRUCTIONS = """\
You are playing OpenTTD as one company, through nttd.

You build transport infrastructure and run vehicles to move cargo and passengers for
profit. You are scored on OpenTTD's own performance rating, which rewards delivered
cargo, vehicle count, station count, profit and money in hand.

Start by calling nttd_observe to see the world, and nttd_actions to look up anything you
have not called before. Prefer nttd_query for what the snapshot does not carry, such as
where a station will fit or which engines exist this year.

Actions are refused for ordinary reasons: too little money, a tile that will not take the
structure, a town with a poor opinion of you. A refusal is information, not a fault.
"""


def build(base_url: str, session_id: str, token: str, host: str, port: int) -> FastMCP:
    """Wire one seat's tools onto a server."""
    mcp = FastMCP("nttd", instructions=_INSTRUCTIONS, host=host, port=port)
    client = ParticipantClient(base_url, session_id, token)

    observe.register(mcp, client)
    act.register(mcp, client)
    step.register(mcp, client)
    query.register(mcp, client)
    catalogue.register(mcp)
    return mcp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="nttd MCP server (one session, one seat)")
    parser.add_argument("--url", default=os.getenv("NTTD_URL", DEFAULT_URL))
    parser.add_argument("--session", default=os.getenv("NTTD_SESSION_ID"))
    parser.add_argument("--token", default=os.getenv("NTTD_PARTICIPANT_TOKEN"))
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("NTTD_MCP_TRANSPORT", "stdio"),
        help="stdio for a client that launches this, http for one that connects to it",
    )
    parser.add_argument("--host", default=os.getenv("NTTD_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NTTD_MCP_PORT", "8100")))
    return parser.parse_args()


def main() -> None:
    """Entry point for ``python -m nttd.mcp.server``."""
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()

    # Checked here rather than on the first tool call. Under stdio a missing token
    # surfaces as every tool failing with a 401, which reads as nttd being broken.
    missing = [name for name, value in (("--session", args.session), ("--token", args.token)) if not value]
    if missing:
        raise SystemExit(
            f"Missing {' and '.join(missing)}. Get both from `nttd session attach <id>`."
        )

    mcp = build(args.url, args.session, args.token, args.host, args.port)
    logger.info(
        "nttd MCP serving session %s over %s (nttd at %s)", args.session, args.transport, args.url,
    )
    mcp.run(transport="streamable-http" if args.transport == "http" else "stdio")


if __name__ == "__main__":
    main()
