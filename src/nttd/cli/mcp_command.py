"""``nttd mcp`` -- serve one session to an MCP client."""

from __future__ import annotations

from typing import Annotated

import typer

from nttd.cli.helpers import console


def mcp(
    session_id: Annotated[str, typer.Argument(help="Session to play")],
    token: Annotated[
        str, typer.Option("--token", "-t", help="Participant token, from `nttd session attach`"),
    ],
    url: Annotated[str, typer.Option("--url", help="nttd server")] = "http://localhost:8000",
    transport: Annotated[
        str,
        typer.Option("--transport", help="stdio, or http for a framework that connects to it"),
    ] = "stdio",
    host: Annotated[str, typer.Option("--host", help="Bind address for --transport http")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port for --transport http")] = 8100,
) -> None:
    """Serve one session over MCP: five tools, enough to play a whole game.

    One server is one seat. It holds a single session and a single participant token,
    so no tool takes a session argument and no client can act for another company.

    Examples:
      nttd mcp ses_abc --token tok_123                    stdio, for a client that
                                                          launches this as a subprocess
      nttd mcp ses_abc --token tok_123 --transport http   for a framework that connects
                                                          to a server already running
    """
    if transport not in ("stdio", "http"):
        console.print(f"[red]Unknown transport:[/] {transport}. Use stdio or http.")
        raise typer.Exit(code=1)

    from nttd.mcp.server import build  # noqa: PLC0415

    server = build(url, session_id, token, host, port)

    # stdio speaks the protocol on stdout, so a banner there would corrupt the stream.
    if transport == "http":
        console.print(
            f"nttd MCP serving [bold]{session_id}[/] on http://{host}:{port} "
            f"(nttd at {url})"
        )
    server.run(transport="streamable-http" if transport == "http" else "stdio")
