"""nttd agent subcommands — register, start, stop, list."""

from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from nttd.cli.helpers import check_server, console, get_base_url, load_instructions

agent_app = typer.Typer(help="Agent registration and control")


@agent_app.command("register")
def agent_register(
    session_id: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    agent_id: Annotated[str, typer.Option("--agent-id", "-a", help="Agent identifier")],
    company_id: Annotated[int, typer.Option("--company-id", "-c", help="Company ID (0-14)")],
    framework: Annotated[str, typer.Option("--framework", "-f", help="openai | langchain | passthrough")] = "openai",
    model: Annotated[str, typer.Option("--model", "-m", help="LLM model name")] = "gpt-4o",
    instructions_file: Annotated[
        Optional[str], typer.Option("--instructions-file", help="Path to instructions file"),
    ] = None,
    instructions: Annotated[str, typer.Option("--instructions", help="Inline system prompt")] = "",
    poll_interval: Annotated[float, typer.Option("--poll-interval", help="Seconds between cycles")] = 5.0,
    observation_mode: Annotated[str, typer.Option("--observation-mode", help="compact | full")] = "compact",
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Register an agent with the gameloop for a session.

    Examples:
      nttd agent register --session ses_abc --agent-id bus --company-id 0 --framework openai
      nttd agent register -s ses_abc -a rail -c 1 -f langchain -m gpt-4o-mini
    """
    import requests

    url = base_url or get_base_url()
    check_server(url)

    agent_instructions = instructions
    if instructions_file:
        agent_instructions = load_instructions(instructions_file)

    payload = {
        "agent_id": agent_id,
        "company_id": company_id,
        "framework": framework,
        "model": model,
        "instructions": agent_instructions,
        "observation_mode": observation_mode,
        "poll_interval": poll_interval,
    }

    resp = requests.post(
        f"{url}/sessions/{session_id}/gameloop/agents/register",
        json=payload,
        timeout=10,
    )
    if resp.status_code == 404:
        console.print(f"[red]Session {session_id} not found or not running[/]")
        raise typer.Exit(1)
    resp.raise_for_status()
    data = resp.json()

    console.print(Panel(
        f"[bold]Connection ID:[/] [cyan]{data.get('connection_id', '?')}[/]\n"
        f"[bold]Agent:[/]         {agent_id}\n"
        f"[bold]Company:[/]       {company_id}\n"
        f"[bold]Framework:[/]     {framework}\n"
        f"[bold]Model:[/]         {model}",
        title="Agent registered",
    ))
    console.print(f"\nStart: [cyan]nttd agent start --session {session_id} --agent-id {agent_id}[/]")


@agent_app.command("start")
def agent_start(
    session_id: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    agent_id: Annotated[str, typer.Option("--agent-id", "-a", help="Agent ID to start")],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Start an agent's observe-decide-interpret-execute cycle loop."""
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.post(
        f"{url}/sessions/{session_id}/gameloop/agents/{agent_id}/start",
        timeout=10,
    )
    if resp.status_code == 404:
        console.print(f"[red]Agent {agent_id} not found in session {session_id}[/]")
        raise typer.Exit(1)
    resp.raise_for_status()

    console.print(f"[green]Agent {agent_id} started in session {session_id}[/]")


@agent_app.command("stop")
def agent_stop(
    session_id: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    agent_id: Annotated[str, typer.Option("--agent-id", "-a", help="Agent ID to stop")],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Stop an agent's cycle loop."""
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.post(
        f"{url}/sessions/{session_id}/gameloop/agents/{agent_id}/stop",
        timeout=10,
    )
    if resp.status_code == 404:
        console.print(f"[red]Agent {agent_id} not found in session {session_id}[/]")
        raise typer.Exit(1)
    resp.raise_for_status()

    console.print(f"[yellow]Agent {agent_id} stopped in session {session_id}[/]")


@agent_app.command("list")
def agent_list(
    session_id: Annotated[str, typer.Option("--session", "-s", help="Session ID")],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """List all agents registered in a session's gameloop."""
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.get(
        f"{url}/sessions/{session_id}/gameloop/agents",
        timeout=10,
    )
    if resp.status_code == 404:
        console.print(f"[red]Session {session_id} not found or not running[/]")
        raise typer.Exit(1)
    resp.raise_for_status()
    agents = resp.json()

    if not agents:
        console.print("[dim]No agents registered.[/]")
        return

    table = Table("Agent ID", "Company", "Framework", "Model", "Status", "Cycles")
    for a in agents:
        status = a.get("status", "?")
        status_str = f"[green]{status}[/]" if status == "running" else f"[dim]{status}[/]"
        table.add_row(
            a.get("agent_id", "?"),
            str(a.get("company_id", "?")),
            a.get("framework", "?"),
            a.get("model", "?"),
            status_str,
            str(a.get("cycle_count", 0)),
        )
    console.print(table)
