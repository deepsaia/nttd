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

from nttd.config.scenario_config import DEFAULT_OBJECTIVE
from nttd.mcp.game_session import STEPPED, GameSession
from nttd.mcp.participant_client import ParticipantClient
from nttd.mcp.tools import act, batch_round, focus, list_commands, observe, query

INSTRUCTIONS = (
    'You are part of a transport company in OpenTTD.\n'
    'The company transports cargo and passengers by aircraft, ship, road, or train, '
    'between towns and industries.\n'
    '\n'
    'OBJECTIVE\n'
    'Your goal is to {objective}\n'
    '\n'
    'Note:\n'
    '- The game episode lasts {days} game days.\n'
    '- The game is scored over the whole episode, but an episode is only valid if you '
    'reach the end of the game episode.\n'
    '- The game episode may end earlier if the company goes bankrupt.\n'
    '\n'
    'COMPANY\n'
    'The company can use four transport modes: aircraft, ship, train and road.\n'
    'Bridges can be used with rail, road, or water. Tunnels and paths can be used with '
    'rail or road.\n'
    '\n'
    'TURNS AND COMMANDS\n'
    '{turns}- A connection command fails if there is no possible route between its '
    'endpoints. Construction can also succeed only partially. \n'
    '\n'
    'GAME REPORT\n'
    '\n'
    '{report}\n'
    '\n'
    'It includes:\n'
    "- company's cash\n"
    '- loan balance\n'
    '- loan limit\n'
    '- company value (calculated as max(1, cash - loan + total station value + 1.5 x '
    'total current vehicle worth))\n'
    '- performance rating (range: 0-1000)\n'
    '- previous quarter revenue\n'
    '{date}- the outcome of each command you submitted\n'
)

OBJECTIVES = {
    "global": "run a profitable company.",
    "cargo": "Maximize the total number of cargo the company delivers over the game episode.",
    "rating": (
        "Maximize the company's performance rating at the end of the game episode.\n"
        '\n'
        'The game computes the rating on the first day of each quarter and reports it as '
        'performance_rating. It goes from 0 to 1000 and is the sum of nine parts. Each part '
        'grows in proportion from 0 to its maximum, which is reached at the target shown:\n'
        '\n'
        '- cargo delivered in the last four quarters: 400 points at 40,000 units\n'
        '- vehicles whose profit last year was positive: 100 points at 120 vehicles\n'
        '- station facilities that loaded or unloaded cargo in the last 20 days: 100 points '
        'at 80 facilities\n'
        '- lowest profit last year among vehicles older than two years: 100 points at 10,000\n'
        '- lowest quarterly income minus expenses over the last twelve quarters: 50 points at '
        '50,000\n'
        '- highest quarterly income minus expenses over the last twelve quarters: 100 points '
        'at 100,000\n'
        '- cargo types delivered in the last quarter: 50 points at 8 types\n'
        '- cash: 50 points at 10,000,000\n'
        '- loan: 50 points at a loan of 0, falling to 0 points at a loan of 250,000 or more\n'
        '\n'
        'Vehicle worth, station worth and company value are not part of the rating.'
    ),
    "value": (
        "Maximize the company's value at the end of the game episode:\n"
        '\n'
        'company value = max(1, cash - loan + total station value + 1.5 × total current '
        'vehicle worth)\n'
        '\n'
        'Values below 1 are reported as 1. Taking a loan increases cash and loan equally, so '
        'it does not directly change company value.'
    ),
}

TURNS = {
    "async_realtime": """- Commands run as soon as they reach the game.
- The game clock never stops. Game days pass while you think.
""",
    "heartbeat": """- The game advances autonomously. Each game day it runs the commands that arrived during that day.
- The game goes on while you think, so game days might pass during your turn.
""",
    "stepped": (
        '- The game only advances when it receives a command, in which case all the commands '
        'that arrived in that game day are executed and one game day passes. \n'
        '    -The day still passes if all commands fail.\n'
    ),
}

REPORTS = {
    "stepped": "The report shows the world after the game day in which your commands ran.",
    "heartbeat": (
        'The report shows the world at the moment your commands were accepted. They run on '
        'the next game day, so their effects appear in later reports.'
    ),
    "async_realtime": (
        'The report shows the world at the moment your commands were accepted. Effects of '
        'commands that have not run yet appear in later reports.'
    ),
}

DATE_REALTIME = "- game date\n"
DATE = "- game date and number of game days remaining, out of the {days} game days of the episode\n"


def instructions_for(mode: str, objective: str, episode_days: int) -> str:
    """The connection text for a session's mode, objective and episode length."""
    if objective not in OBJECTIVES:
        logger.warning("Unknown objective %r; using %s for MCP instructions", objective, DEFAULT_OBJECTIVE)
        objective = DEFAULT_OBJECTIVE
    realtime = mode == "async_realtime"
    return INSTRUCTIONS.format(
        objective=OBJECTIVES[objective],
        days=episode_days,
        turns=TURNS[mode],
        report=REPORTS[mode],
        date=DATE_REALTIME if realtime else DATE.format(days=episode_days),
    )


logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8000"
DEFAULT_TAG = "agent"


def fetch_status(base_url: str, session_id: str) -> dict:
    """Read the session's public status once, before the tools are registered: the
    act text depends on the mode, and the instructions on the mode, the objective and
    the episode length."""
    response = httpx.get(
        f"{base_url.rstrip('/')}/v1/public/sessions/{session_id}/status", timeout=30.0
    )
    response.raise_for_status()
    return response.json()


def build(
    base_url: str,
    session_id: str,
    token: str | None,
    host: str,
    port: int,
    mode: str = STEPPED,
    objective: str = DEFAULT_OBJECTIVE,
    episode_days: int = 0,
    company_id: int = 0,
    days: int | None = None,
    reward: bool = False,
    seed: int | None = None,
    default_tag: str = DEFAULT_TAG,
) -> FastMCP:
    """Wire one session's tools onto a server."""
    mcp = FastMCP(
        "nttd",
        instructions=instructions_for(mode, objective, episode_days),
        host=host,
        port=port,
    )
    client = ParticipantClient(base_url, session_id, token)
    session = GameSession(
        client,
        company_id=company_id,
        days=days,
        reward_enabled=reward,
        seed=seed,
        default_tag=default_tag,
    )
    session.mode = mode

    observe.register(mcp, session)
    act.register(mcp, session)
    query.register(mcp, session)
    list_commands.register(mcp, session)
    focus.register(mcp, session)
    batch_round.register(mcp, session)
    return mcp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="nttd MCP server (one session, one company)"
    )
    parser.add_argument("--url", default=os.getenv("NTTD_URL", DEFAULT_URL))
    parser.add_argument("--session", default=os.getenv("NTTD_SESSION_ID"))
    parser.add_argument(
        "--token",
        default=os.getenv("NTTD_PARTICIPANT_TOKEN"),
        help="Participant token. Not needed by a session that issued none.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("NTTD_MCP_TRANSPORT", "stdio"),
        help="stdio for a client that launches this, http for one that connects to it",
    )
    parser.add_argument("--host", default=os.getenv("NTTD_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("NTTD_MCP_PORT", "8100"))
    )
    parser.add_argument("--company", type=int, default=0, help="The company to play.")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Game days per step. Unset uses the scenario's step size.",
    )
    parser.add_argument(
        "--reward",
        action="store_true",
        help="Add the change in money minus loan to every act reply.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for the random order of the agents in a round.",
    )
    parser.add_argument(
        "--default-tag",
        default=DEFAULT_TAG,
        help="Agent tag used when a call names none.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for ``python -m nttd.mcp``."""
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    if not args.session:
        raise SystemExit("Missing --session. Get the id from `nttd session list`.")

    status = fetch_status(args.url, args.session)
    mode = str(status.get("mode", STEPPED))
    mcp = build(
        args.url,
        args.session,
        args.token,
        args.host,
        args.port,
        mode=mode,
        objective=str(status.get("objective", DEFAULT_OBJECTIVE)),
        episode_days=int(status.get("episode_days") or 0),
        company_id=args.company,
        days=args.days,
        reward=args.reward,
        seed=args.seed,
        default_tag=args.default_tag,
    )
    logger.info(
        "nttd MCP serving session %s (%s mode) over %s (nttd at %s)",
        args.session,
        mode,
        args.transport,
        args.url,
    )
    mcp.run(transport="streamable-http" if args.transport == "http" else "stdio")


if __name__ == "__main__":
    main()
