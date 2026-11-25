"""``nttd mcp`` -- serve one session to an MCP client."""

from __future__ import annotations

from typing import Annotated

import typer

from nttd.cli.helpers import console
from nttd.config.scenario_config import DEFAULT_OBJECTIVE
from nttd.mcp.game_session import STEPPED
from nttd.mcp.server import DEFAULT_TAG, build, fetch_status


def mcp(
    session_id: Annotated[str, typer.Argument(help="Session to play")],
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            help="Participant token, from `nttd session attach`. Not needed by a session that issued none.",
        ),
    ] = None,
    url: Annotated[str, typer.Option("--url", help="nttd server")] = "http://localhost:8000",
    transport: Annotated[
        str,
        typer.Option("--transport", help="stdio, or http for a framework that connects to it"),
    ] = "stdio",
    host: Annotated[str, typer.Option("--host", help="Bind address for --transport http")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port for --transport http")] = 8100,
    company: Annotated[int, typer.Option("--company", help="The company to play")] = 0,
    days: Annotated[
        int | None, typer.Option("--days", help="Game days per step. Unset uses the scenario's step size")
    ] = None,
    reward: Annotated[
        bool, typer.Option("--reward/--no-reward", help="Add the change in money minus loan to every act reply")
    ] = False,
    seed: Annotated[
        int | None, typer.Option("--seed", help="Seed for the random order of the agents in a round")
    ] = None,
    default_tag: Annotated[
        str, typer.Option("--default-tag", help="Agent tag used when a call names none")
    ] = DEFAULT_TAG,
) -> None:
    """Serve one session over MCP: six tools, enough to play a whole game.

    One server plays one session and one company. The game commands arrive as enums
    in the tool schemas, so no client has to learn them from a prompt.

    Examples:
      nttd mcp ses_abc                                    stdio, for a client that
                                                          launches this as a subprocess
      nttd mcp ses_abc --transport http --port 8010       for a framework that connects
                                                          to a server already running
    """
    if transport not in ("stdio", "http"):
        console.print(f"[red]Unknown transport:[/] {transport}. Use stdio or http.")
        raise typer.Exit(code=1)

    status = fetch_status(url, session_id)
    mode = str(status.get("mode", STEPPED))
    server = build(
        url,
        session_id,
        token,
        host,
        port,
        mode=mode,
        objective=str(status.get("objective", DEFAULT_OBJECTIVE)),
        episode_days=int(status.get("episode_days") or 0),
        company_id=company,
        days=days,
        reward=reward,
        seed=seed,
        default_tag=default_tag,
    )

    # stdio speaks the protocol on stdout, so a banner there would corrupt the stream.
    if transport == "http":
        console.print(f"nttd MCP serving [bold]{session_id}[/] ({mode} mode) on http://{host}:{port} (nttd at {url})")
    server.run(transport="streamable-http" if transport == "http" else "stdio")
