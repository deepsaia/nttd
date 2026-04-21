"""nttd CLI -- command-line interface for managing sessions, agents, and benchmarks.

Why this __init__.py is not empty:

Most __init__.py files in this project are intentionally left empty -- they
just mark a directory as a Python package. This one is different because it
is the CLI entry point. pyproject.toml declares:

    [project.scripts]
    nttd = "nttd.cli:main"

That tells Python "when someone types `nttd` in the terminal, import
nttd.cli and call main()". So this file must define main(), and for
main() to work, the Typer app must already have all its commands registered.

Typer (the CLI framework) builds its command tree at import time:
  - app.command()(fn)   registers a single command like `nttd server`
  - app.add_typer(sub)  registers a command group like `nttd session ...`

If we moved these registrations elsewhere, `nttd --help` would show no
commands. That is why all the imports and registrations live here.

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
  nttd mas neuro-san         Start a neuro-san MAS server
  nttd benchmark             Run a full benchmark from HOCON config
  nttd analyze               Generate session analysis reports
"""

import typer

from nttd.cli.agent_commands import agent_app
from nttd.cli.analyze_command import analyze
from nttd.cli.benchmark_command import benchmark
from nttd.cli.mas_command import mas_app
from nttd.cli.server_command import server
from nttd.cli.session_commands import session_app

app = typer.Typer(
    name="nttd",
    help="nttd -- Agent-agnostic API server for OpenTTD AI simulation",
    no_args_is_help=True,
)

app.add_typer(session_app, name="session")
app.add_typer(agent_app, name="agent")
app.add_typer(mas_app, name="mas")
app.command()(server)
app.command()(benchmark)
app.command()(analyze)


def main() -> None:
    app()
