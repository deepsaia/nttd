"""nttd session subcommands — create, start, stop, list, status."""

from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from nttd.cli.helpers import (
    build_end_conditions_payload,
    check_server,
    console,
    format_end_conditions_brief,
    get_base_url,
)

session_app = typer.Typer(help="Session lifecycle management")


@session_app.command("create")
def session_create(
    config: Annotated[Optional[str], typer.Option("--config", "-c", help="Path to HOCON scenario config")] = None,
    name: Annotated[str, typer.Option("--name", "-n", help="Session name")] = "",
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Create a new session from HOCON config.

    Loads the config, converts map/company settings to OpenTTD RCON settings,
    stores everything in the DB, and returns the session ID.

    Examples:
      nttd session create --config config/scenario.conf
      nttd session create --config config/scenario.conf --name "bus_benchmark"
    """
    import requests

    from nttd.config.scenario_config import load as load_scenario
    from nttd.config.scenario_config import scenario_to_settings

    url = base_url or get_base_url()
    check_server(url)

    from nttd.utils.name_generator import generate_session_name

    cfg = load_scenario(config)
    settings = scenario_to_settings(cfg)
    session_name = name or (cfg.name if cfg.name != "default" else generate_session_name())

    resp = requests.post(
        f"{url}/admin/sessions/new",
        json={"name": session_name, "settings": settings},
        timeout=10,
    )
    resp.raise_for_status()
    session_id = resp.json()["session_id"]

    ec_payload = build_end_conditions_payload(cfg.end_conditions)
    if len(ec_payload) > 1:
        requests.post(
            f"{url}/admin/sessions/{session_id}/end-conditions",
            json=ec_payload,
            timeout=10,
        )

    console.print(Panel(
        f"[bold]Session ID:[/]  [cyan]{session_id}[/]\n"
        f"[bold]Name:[/]        {session_name}\n"
        f"[bold]Config:[/]      {config or 'defaults'}\n"
        f"[bold]Map:[/]         {cfg.map.size_x}x{cfg.map.size_y} {cfg.map.landscape}\n"
        f"[bold]AI opponents:[/] {cfg.companies.num_ai_companies}\n"
        f"[bold]Runtime:[/]     {cfg.runtime.mode} @ {cfg.runtime.game_speed}x\n"
        f"[bold]Agents:[/]      {len(cfg.agents)} configured\n"
        + format_end_conditions_brief(cfg.end_conditions),
        title="Session created",
    ))
    console.print(f"\nNext: [cyan]nttd session start {session_id}[/]")


@session_app.command("start")
def session_start(
    session_id: Annotated[str, typer.Argument(help="Session ID to start")],
    ai_opponents: Annotated[int, typer.Option("--ai-opponents", "-a", help="Number of AI opponents")] = -1,
    agent_companies: Annotated[int, typer.Option(
        "--agent-companies", help="Number of idle company slots for nttd agents",
    )] = -1,
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Start an OpenTTD server for a session.

    Spawns the OpenTTD process, allocates ports, applies settings, and starts the game.
    Use --agent-companies to pre-create idle company slots for nttd-controlled agents.

    Examples:
      nttd session start ses_abc123
      nttd session start ses_abc123 --agent-companies 2
    """
    import requests

    url = base_url or get_base_url()
    check_server(url)

    payload: dict = {"mode": "newgame"}
    if ai_opponents >= 0:
        payload["ai_opponents"] = ai_opponents
    if agent_companies >= 0:
        payload["agent_companies"] = agent_companies

    with console.status("Starting OpenTTD server..."):
        resp = requests.post(
            f"{url}/admin/sessions/{session_id}/start",
            json=payload,
            timeout=30,
        )

    if resp.status_code == 404:
        console.print(f"[red]Session {session_id} not found[/]")
        raise typer.Exit(1)
    if resp.status_code == 409:
        console.print(f"[yellow]Session {session_id} is already running[/]")
        raise typer.Exit(1)
    resp.raise_for_status()

    data = resp.json()
    console.print(Panel(
        f"[bold]Session:[/]    [cyan]{session_id}[/]\n"
        f"[bold]Status:[/]     [green]active[/]\n"
        f"[bold]Game port:[/]  [cyan]{data.get('game_port')}[/]\n"
        f"[bold]Admin port:[/] {data.get('admin_port')}\n"
        f"[bold]PID:[/]        {data.get('pid')}",
        title="Session started",
    ))
    console.print(
        f"\nJoin game: [cyan]127.0.0.1:{data.get('game_port')}[/]"
        f"\nRegister agents: [cyan]nttd agent register --session {session_id} ...[/]"
    )


@session_app.command("stop")
def session_stop(
    session_id: Annotated[str, typer.Argument(help="Session ID to stop")],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Stop a running session and archive it."""
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.post(f"{url}/admin/sessions/{session_id}/stop", timeout=15)
    if resp.status_code == 404:
        console.print(f"[red]Session {session_id} not found[/]")
        raise typer.Exit(1)
    resp.raise_for_status()

    console.print(f"[green]Session {session_id} stopped and archived.[/]")


@session_app.command("list")
def session_list(
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """List all sessions with status."""
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.get(f"{url}/admin/sessions", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    sessions = data.get("sessions", [])

    if not sessions:
        console.print("[dim]No sessions found.[/]")
        return

    table = Table("ID", "Name", "Status", "Game Port", "Created")
    for s in sessions:
        status = s.get("status", "?")
        running = s.get("running", False)
        status_str = f"[green]{status}[/]" if running else f"[dim]{status}[/]"
        table.add_row(
            s.get("session_id", "?"),
            s.get("name", ""),
            status_str,
            str(s.get("game_port") or "—"),
            s.get("created_at", "")[:19],
        )
    console.print(table)


@session_app.command("status")
def session_status(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Show detailed status for a session."""
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.get(f"{url}/admin/sessions/{session_id}", timeout=10)
    if resp.status_code == 404:
        console.print(f"[red]Session {session_id} not found[/]")
        raise typer.Exit(1)
    resp.raise_for_status()
    data = resp.json()

    running = data.get("running", False)
    status_color = "green" if running else "dim"
    lines = [
        f"[bold]Session:[/]    [cyan]{session_id}[/]",
        f"[bold]Name:[/]       {data.get('name', '')}",
        f"[bold]Status:[/]     [{status_color}]{data.get('status', '?')}[/]",
    ]
    if running:
        lines.append(f"[bold]Game port:[/] [cyan]{data.get('game_port')}[/]")
        lines.append(f"[bold]Admin port:[/]{data.get('admin_port')}")
        lines.append(f"[bold]PID:[/]       {data.get('pid')}")

    if data.get("started_at"):
        lines.append(f"[bold]Started:[/]   {data['started_at'][:19]}")
    if data.get("ended_at"):
        lines.append(f"[bold]Ended:[/]     {data['ended_at'][:19]}")

    settings = data.get("settings", {})
    if settings:
        lines.append(f"\n[bold]Settings:[/]  {len(settings)} configured")

    console.print(Panel("\n".join(lines), title="Session Detail"))

    if running:
        try:
            game_resp = requests.get(f"{url}/sessions/{session_id}/status", timeout=5)
            if game_resp.ok:
                game = game_resp.json()
                console.print(Panel(
                    f"[bold]Date:[/]   {game.get('game_date', '?')}\n"
                    f"[bold]Paused:[/] {game.get('paused', '?')}\n"
                    f"[bold]Speed:[/]  {game.get('speed', '?')}x\n"
                    f"[bold]Map:[/]    {game.get('map_width', '?')}x{game.get('map_height', '?')}",
                    title="Game State",
                ))
        except Exception:
            pass
