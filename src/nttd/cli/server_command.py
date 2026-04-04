"""nttd server command."""

import subprocess
import sys
from typing import Annotated

import typer

from nttd.cli.helpers import console


def server(
    host: Annotated[str, typer.Option("--host", "-h", help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code changes")] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="Uvicorn log level")] = "info",
) -> None:
    """Start the nttd API server."""
    cmd = [
        sys.executable, "-m", "uvicorn",
        "nttd.api.app:app",
        "--host", host,
        "--port", str(port),
        "--log-level", log_level,
    ]
    if reload:
        cmd.append("--reload")

    console.print(f"[bold]Starting nttd server[/] on [cyan]http://{host}:{port}[/]")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/]")
