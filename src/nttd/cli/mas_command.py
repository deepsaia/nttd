"""nttd mas command -- start external MAS framework servers.

Each framework subcommand knows how to configure and launch its server.
nttd just sets up paths and env vars -- the framework serves all its
configured agent networks. Which network to talk to is determined by
the endpoint URL in nttd's scenario config.

  nttd mas neuro-san                  # start neuro-san server
  nttd mas langgraph                  # future
  nttd mas crewai                     # future
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from nttd.cli.helpers import console, load_dotenv

mas_app = typer.Typer(
    name="mas",
    help="Start external MAS framework servers for multi-agent benchmarks.",
    no_args_is_help=True,
)


@mas_app.command("neuro-san")
def neuro_san(
    port: Annotated[int, typer.Option("--port", "-p", help="HTTP port")] = 8080,
    env_file: Annotated[str, typer.Option("--env-file", help="Path to .env file")] = ".env",
    mas_dir: Annotated[str, typer.Option(
        "--mas-dir", help="Path to MAS example directory with registries/ and coded_tools/",
    )] = "examples/neuro_san_mas",
    log_level: Annotated[str, typer.Option("--log-level", help="Log level")] = "INFO",
    nttd_url: Annotated[str, typer.Option(
        "--nttd-url", help="nttd API URL for coded tool callbacks",
    )] = "http://localhost:8000",
    mcp: Annotated[bool, typer.Option("--mcp/--no-mcp", help="Enable MCP protocol")] = False,
) -> None:
    """Start a neuro-san server serving all agent networks in the manifest.

    Loads API keys from .env, sets neuro-san paths, and starts the server.
    The server serves all networks listed in registries/manifest.hocon.
    Which network nttd talks to is determined by the endpoint URL in the
    scenario config (e.g. /api/v1/rail_coordinator/streaming_chat).

    Examples:
      nttd mas neuro-san
      nttd mas neuro-san --port 9090
      nttd mas neuro-san --env-file .env.prod
    """
    project_root = Path.cwd()
    mas_path = Path(mas_dir)
    if not mas_path.is_absolute():
        mas_path = project_root / mas_path

    registries_dir = mas_path / "registries"
    coded_tools_dir = mas_path / "coded_tools"
    manifest_file = registries_dir / "manifest.hocon"

    if not manifest_file.exists():
        console.print(f"[red]Manifest not found:[/] {manifest_file}")
        console.print(f"Expected at: {mas_path}/registries/manifest.hocon")
        raise typer.Exit(code=1)

    env_path = Path(env_file)
    if not env_path.is_absolute():
        env_path = project_root / env_path
    dotenv = load_dotenv(env_path)
    if dotenv:
        console.print(f"  Loaded {len(dotenv)} var(s) from [cyan]{env_path.name}[/]")
    elif env_path.exists():
        console.print(f"  [yellow]{env_path.name} is empty[/]")
    else:
        console.print(f"  [yellow]{env_path.name} not found, using current env only[/]")

    env = {**os.environ, **dotenv}
    env["AGENT_MANIFEST_FILE"] = str(manifest_file)
    env["AGENT_TOOL_PATH"] = str(coded_tools_dir)
    env["AGENT_HTTP_PORT"] = str(port)
    env["AGENT_MCP_ENABLE"] = "true" if mcp else "false"
    env["AGENT_SERVICE_LOG_LEVEL"] = log_level
    env["NTTD_API_URL"] = nttd_url

    python_paths = [str(coded_tools_dir)]
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_paths)

    cmd = [sys.executable, "-m", "neuro_san.service.main_loop.server_main_loop"]

    console.print()
    console.print("[bold]Neuro-SAN MAS Server[/]")
    console.print(f"  Manifest:   {manifest_file}")
    console.print(f"  Tools:      {coded_tools_dir}")
    console.print(f"  Port:       [cyan]{port}[/]")
    console.print(f"  nttd URL:   {nttd_url}")
    console.print(f"  MCP:        {'enabled' if mcp else 'disabled'}")
    console.print()

    console.print(f"Starting on [cyan]http://localhost:{port}[/] ...")
    console.print()

    try:
        subprocess.run(cmd, env=env, check=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Neuro-SAN server stopped.[/]")
    except FileNotFoundError:
        console.print("[red]neuro-san not installed.[/] Install with: pip install neuro-san")
        raise typer.Exit(code=1)
