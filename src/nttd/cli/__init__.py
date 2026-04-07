"""nttd CLI — command-line interface for managing sessions, agents, and benchmarks.

Commands:
  nttd server                Start the nttd API server (uvicorn)
  nttd session create        Create a new session from HOCON config
  nttd session start         Start an OpenTTD server for a session
  nttd session stop          Stop a running session
  nttd session list          List all sessions
  nttd session status        Show detailed session status
  nttd agent register        Register an agent with the gameloop
  nttd agent start           Start an agent's cycle loop
  nttd agent stop            Stop an agent's cycle loop
  nttd agent list            List agents for a session
  nttd benchmark             Run a full benchmark from HOCON config
"""

import typer

from nttd.cli.agent_commands import agent_app
from nttd.cli.benchmark_command import benchmark
from nttd.cli.server_command import server
from nttd.cli.session_commands import session_app

app = typer.Typer(
    name="nttd",
    help="nttd -- Agent-agnostic API server for OpenTTD AI simulation",
    no_args_is_help=True,
)

app.add_typer(session_app, name="session")
app.add_typer(agent_app, name="agent")
app.command()(server)
app.command()(benchmark)


def main() -> None:
    app()
