"""nttd server command."""

import socket
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from nttd.cli.helpers import apply_dotenv, console
from nttd.runtime.server_lock import ServerLock
from nttd.store import session_paths


def _port_is_taken(host: str, port: int) -> bool:
    """Whether something is already listening there.

    Checked BEFORE the server process is spawned, because uvicorn binds its socket AFTER
    running the application's startup hooks. A server that got that far and then failed to
    bind had already adopted every live session and took them down on its way out. ServerLock
    is the guarantee against that; this is what turns the common case into one readable line
    instead of a stack trace.

    SO_REUSEADDR so a port merely in TIME_WAIT does not read as occupied, which would refuse
    to restart a server for a minute after stopping it.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
    except OSError:
        return True
    finally:
        probe.close()
    return False


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

    # Both checks happen HERE, before a child process exists, because the failure has to be
    # one readable line rather than a stack trace through uvicorn. The lock inside the
    # application is still the authority; this only makes the ordinary case legible.
    sessions_dir = session_paths.sessions_dir()
    if _port_is_taken(host, port):
        console.print(
            f"[red]A server is already running on {host}:{port}.[/] Nothing was started, and "
            "no session was touched."
        )
        held_by = ServerLock(sessions_dir).holder()
        if held_by is not None:
            console.print(f"  It is pid {held_by}, serving [cyan]{sessions_dir}[/].")
        console.print(
            "  One server serves any number of sessions, so a second one is rarely wanted. "
            "Use [cyan]--port[/] and [cyan]NTTD_SESSIONS_DIR[/] if it is."
        )
        raise typer.Exit(1)

    # A free port is not enough. Two servers on different ports and one sessions directory
    # would both recover the same OpenTTD processes, and either could stop the other's runs.
    # Taken and released immediately: the server process acquires it for real a moment later,
    # and if something wins the race in between, its own lock still refuses.
    probe_lock = ServerLock(sessions_dir)
    try:
        probe_lock.acquire()
    except RuntimeError as busy:
        console.print(f"[red]{busy}[/]")
        console.print("Nothing was started, and no session was touched.")
        raise typer.Exit(1) from busy
    probe_lock.release()

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
        # No check=True. It raises CalledProcessError, which typer renders as a stack trace
        # through nttd's own frames, and the reader then goes looking for a bug in the CLI. The
        # child has already said what went wrong; this only needs to not bury it.
        finished = subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/]")
        return
    if finished.returncode:
        console.print(f"[red]The server exited with status {finished.returncode}.[/]")
        raise typer.Exit(finished.returncode)
