"""Typer app construction and command registration -- the `nttd` entry point.

Typer builds its command tree at import time, so every command must be
registered here before ``main()`` runs:
  - app.command()(fn)   registers a single command like `nttd server`
  - app.add_typer(sub)  registers a command group like `nttd session ...`

This lives in a module rather than in ``cli/__init__.py`` because package
``__init__.py`` files in this project hold no logic. ``pyproject.toml`` points
the console script at ``nttd.cli.app:main``.

Commands:
  nttd server                Start the nttd API server (uvicorn)
  nttd session create        Create a new session from HOCON config
  nttd session start         Start an OpenTTD server for a session
  nttd session stop          Stop a running session
  nttd session list          List all sessions
  nttd session status        Show detailed session status
  nttd session attach        Show what a runner needs to play a session
  nttd scenario validate     Check a scenario without running it
  nttd scenario profile      Show the rules a scored scenario must satisfy
  nttd actions               Show the action surface, generated from the GameScript
  nttd benchmark             Stand up a benchmark task and wait for it to end
  nttd result                Show the scored result record for a session
  nttd submit                Package a session into a submission bundle
  nttd verify                Self-check a submission bundle
  nttd publish               File a bundle on the board as a pull request
  nttd analyze               Generate session analysis reports
  nttd monitor               Watch sessions in a browser while they run
  nttd runex                 Run an experiment against a live session
"""

import typer

from nttd.cli.actions_command import actions
from nttd.cli.analyze_command import analyze
from nttd.cli.benchmark_command import benchmark
from nttd.cli.mcp_command import mcp
from nttd.cli.monitor_command import monitor
from nttd.cli.publish_command import publish
from nttd.cli.result_command import result
from nttd.cli.runex_command import runex
from nttd.cli.scenario_commands import scenario_app
from nttd.cli.server_command import server
from nttd.cli.session_commands import session_app
from nttd.cli.submit_command import submit
from nttd.cli.verify_command import verify

app = typer.Typer(
    name="nttd",
    help="nttd -- Agent-agnostic API server for OpenTTD AI simulation",
    no_args_is_help=True,
)

app.add_typer(session_app, name="session")
app.add_typer(scenario_app, name="scenario")
app.command()(server)
app.command()(benchmark)
app.command()(result)
app.command()(submit)
app.command()(publish)
app.command()(verify)
app.command()(analyze)
app.command()(actions)
app.command()(mcp)
app.command(
    # Everything after the command name belongs to the launcher, not to typer here, and that
    # includes --help: intercepting it would print this doorway's help for a question about
    # the thing behind it.
    add_help_option=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(runex)
app.command()(monitor)


def main() -> None:
    app()
