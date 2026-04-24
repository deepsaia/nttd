"""nttd server command."""

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from nttd.cli.helpers import apply_dotenv, console


def server(
    host: Annotated[str, typer.Option("--host", "-h", help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code changes")] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="Uvicorn log level")] = "info",
    env_file: Annotated[str, typer.Option("--env-file", help="Path to .env file")] = ".env",
) -> None:
    """Start the nttd API server.

    Loads environment variables from .env (e.g. AGENT_MANIFEST_FILE,
    AGENT_TOOL_PATH) so the gameloop can resolve MAS agent metadata.
    """
    dotenv = apply_dotenv(Path(env_file))
    if dotenv:
        console.print(f"  Loaded {len(dotenv)} var(s) from [cyan]{env_file}[/]")

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
