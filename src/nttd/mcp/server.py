"""The nttd MCP server: six tools that play one session as one company.

    nttd mcp <session_id> [--url ...] [--transport stdio|http] [--port 8100]
    python -m nttd.mcp --session <session_id> ...

    observe        read the world
    act            change it, in every game mode
    query          ask something the state does not carry
    list_commands  look up what a command or query takes
    focus          choose the part of the map the replies describe
    batch_round    the calls of many agents for one round, for an orchestrator

The game commands are not tools. They arrive as enums in the schemas of ``act`` and
``query``, built from the action manifest, so a name outside the manifest cannot be
sent and none has to be learned from a prompt.

Both transports exist because both kinds of client matter: stdio for an agent that
launches the server as a subprocess, and streamable HTTP for a framework that connects
to one already running. One server plays one session and one company.
"""

from __future__ import annotations

import argparse
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

from nttd.mcp.game_session import STEPPED, GameSession
from nttd.mcp.participant_client import ParticipantClient
from nttd.mcp.tools import act, batch_round, focus, list_commands, observe, query

INSTRUCTIONS = """\
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


logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8000"
DEFAULT_TAG = "agent"


def fetch_mode(base_url: str, session_id: str) -> str:
    """Read the session's mode once, before the tools are registered: the act text
    depends on it."""
    response = httpx.get(f"{base_url.rstrip('/')}/v1/public/sessions/{session_id}/status", timeout=30.0)
    response.raise_for_status()
    return str(response.json().get("mode", STEPPED))


def build(
    base_url: str,
    session_id: str,
    token: str | None,
    host: str,
    port: int,
    mode: str = STEPPED,
    company_id: int = 0,
    days: int | None = None,
    reward: bool = False,
    seed: int | None = None,
    default_tag: str = DEFAULT_TAG,
) -> FastMCP:
    """Wire one session's tools onto a server."""
    mcp = FastMCP("nttd", instructions=INSTRUCTIONS, host=host, port=port)
    client = ParticipantClient(base_url, session_id, token)
    session = GameSession(client, company_id=company_id, days=days, reward_enabled=reward, seed=seed, default_tag=default_tag)
    session.mode = mode

    observe.register(mcp, session)
    act.register(mcp, session)
    query.register(mcp, session)
    list_commands.register(mcp, session)
    focus.register(mcp, session)
    batch_round.register(mcp, session)
    return mcp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="nttd MCP server (one session, one company)")
    parser.add_argument("--url", default=os.getenv("NTTD_URL", DEFAULT_URL))
    parser.add_argument("--session", default=os.getenv("NTTD_SESSION_ID"))
    parser.add_argument("--token", default=os.getenv("NTTD_PARTICIPANT_TOKEN"), help="Participant token. Not needed by a session that issued none.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("NTTD_MCP_TRANSPORT", "stdio"),
        help="stdio for a client that launches this, http for one that connects to it",
    )
    parser.add_argument("--host", default=os.getenv("NTTD_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("NTTD_MCP_PORT", "8100")))
    parser.add_argument("--company", type=int, default=0, help="The company to play.")
    parser.add_argument("--days", type=int, default=None, help="Game days per step. Unset uses the scenario's step size.")
    parser.add_argument("--reward", action="store_true", help="Add the change in money minus loan to every act reply.")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random order of the agents in a round.")
    parser.add_argument("--default-tag", default=DEFAULT_TAG, help="Agent tag used when a call names none.")
    return parser.parse_args()


def main() -> None:
    """Entry point for ``python -m nttd.mcp``."""
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    if not args.session:
        raise SystemExit("Missing --session. Get the id from `nttd session list`.")

    mode = fetch_mode(args.url, args.session)
    mcp = build(
        args.url, args.session, args.token, args.host, args.port,
        mode=mode, company_id=args.company, days=args.days, reward=args.reward,
        seed=args.seed, default_tag=args.default_tag,
    )
    logger.info(
        "nttd MCP serving session %s (%s mode) over %s (nttd at %s)", args.session, mode, args.transport, args.url,
    )
    mcp.run(transport="streamable-http" if args.transport == "http" else "stdio")


if __name__ == "__main__":
    main()
