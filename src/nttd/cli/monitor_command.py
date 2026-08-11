"""The ``nttd monitor`` command."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from nttd.cli.helpers import console
from nttd.monitor import server


def monitor(
    port: Annotated[int, typer.Option("--port", "-p", help="Port to serve on")] = server.DEFAULT_PORT,
    host: Annotated[str, typer.Option("--host", help="Address to bind")] = server.DEFAULT_HOST,
    sessions_dir: Annotated[
        str, typer.Option("--sessions-dir", help="Where session directories live"),
    ] = "",
    limit: Annotated[
        int, typer.Option("--limit", help="How many recent sessions to list"),
    ] = 40,
    base_url: Annotated[
        str, typer.Option("--url", help="nttd server URL, used only to stop a session"),
    ] = "http://127.0.0.1:8000",
    stop_on_anomaly: Annotated[
        bool,
        typer.Option(
            "--stop-on-anomaly",
            help="Stop a live session that trips a bad rule. Off by default.",
        ),
    ] = False,
) -> None:
    """Watch sessions in a browser: charts, a map, and what is going wrong.

    Reads session directories from disk, so it works on a running session, on one that
    has finished, and on a session directory copied from somewhere else. Nothing needs to
    be running for the ended ones.

    Examples:
      nttd monitor
      nttd monitor --port 4300 --limit 10
      nttd monitor --stop-on-anomaly
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # The loader announces every session it reads. That is right for a one shot report
    # and wrong here: this reloads every session on every request, and the page refreshes
    # itself every ten seconds, so at INFO the one line that matters (a rule tripping)
    # would arrive buried in hundreds.
    logging.getLogger("nttd.analysis.loader").setLevel(logging.WARNING)
    console.print(f"[green]nttd monitor[/] on [cyan]http://{host}:{port}[/]  (ctrl-c to stop)")
    if stop_on_anomaly:
        console.print(
            "[yellow]Armed:[/] a live session tripping a bad rule will be stopped.",
        )
    server.serve(
        sessions_dir=Path(sessions_dir) if sessions_dir else None,
        host=host,
        port=port,
        session_limit=limit,
        base_url=base_url,
        stop_on_anomaly=stop_on_anomaly,
    )
