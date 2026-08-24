"""nttd session subcommands: create, start, stop, list, status."""

from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from nttd.cli.helpers import (
    check_server,
    console,
    format_end_conditions_brief,
    get_base_url,
    resolve_session,
    session_option,
)
from nttd.constants import MAX_CONTESTANT_COMPANIES

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
      nttd session create --config config/benchmark/t2_256_flat_1001_realtime.conf
      nttd session create --config config/benchmark/t2_256_flat_1001_realtime.conf --name "my_run"
    """
    import requests

    from nttd.config.scenario_config import load as load_scenario
    from nttd.config.scenario_config import scenario_to_settings

    url = base_url or get_base_url()
    check_server(url)

    # A bad path is a typo, not a crash. Reported as one line rather than a traceback,
    # while still refusing: the defaults behind a mistyped path are a random seed and a
    # different runtime mode, so quietly using them is worse than stopping.
    try:
        cfg = load_scenario(config)
    except (FileNotFoundError, ValueError) as bad_config:
        console.print(f"[red]{bad_config}[/]")
        raise typer.Exit(code=1) from None
    settings = scenario_to_settings(cfg)

    # The server mints the id when no name is sent, and that is the only place it should be
    # minted: a session has one identity. Passing the scenario's own name here is what made
    # ids read benchmark_benchmark-t1-256-flat-1001-stepped, and a client-minted name and a
    # server-minted id disagreeing is the bug the single id was introduced to end.
    session_name = name

    # config_path only: the server loads the scenario itself. Sending the whole
    # settings dict is refused with a 400, because it carries _scored and the
    # profile-derived keys that a client may not supply -- they decide whether the
    # run is scored and what bounds it.
    resp = requests.post(
        f"{url}/v1/operator/admin/sessions/new",
        json={"name": session_name, "settings": {}, "config_path": config or ""},
        timeout=10,
    )
    if not resp.ok:
        console.print(f"[red]Could not create session:[/] {resp.status_code}")
        console.print(f"[dim]{resp.text[:300]}[/]")
        raise typer.Exit(code=1)
    session_id = resp.json()["session_id"]

    # End conditions are stored in settings and applied at session start
    # Read display values from settings (already parsed from raw config)
    map_x = 2 ** int(settings.get("game_creation.map_x", "8"))
    map_y = 2 ** int(settings.get("game_creation.map_y", "8"))
    ai_count = settings.get("difficulty.max_no_competitors", "0")
    seed = settings.get("_map_seed")

    console.print(Panel(
        # No separate Name row. The id IS the name, and a row that repeated it, or sat
        # empty when nothing was passed, only invited the question of which one to use.
        f"[bold]Session:[/]     [cyan]{session_id}[/]\n"
        f"[bold]Config:[/]      {config or 'defaults'}\n"
        f"[bold]Map:[/]         {map_x}x{map_y}\n"
        f"[bold]Seed:[/]        "
        + (f"[cyan]{seed}[/]" if seed else "[yellow]random (not reproducible)[/]") + "\n"
        f"[bold]Idle slots:[/] {ai_count}\n"
        f"[bold]Runtime:[/]     {cfg.runtime.mode}\n"
        + format_end_conditions_brief(cfg.end_conditions),
        title="Session created",
    ))
    console.print(f"\nNext: [cyan]nttd session start -s {session_id}[/]")


@session_app.command("start")
def session_start(
    session: Annotated[str, session_option()],
    ai_opponents: Annotated[int, typer.Option("--ai-opponents", "-a", help="Extra idle company slots")] = -1,
    agent_companies: Annotated[int, typer.Option(
        "--agent-companies", help="Company slots for a contestant: 0 or 1",
    )] = -1,
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Start an OpenTTD server for a session.

    Spawns the OpenTTD process, allocates ports, applies settings, and starts the game.
    Use --agent-companies 1 to pre-create the company a contestant plays.

    One contestant company per session, in every mode. Several agents playing together
    drive that one company: their orchestrator decides what it does and submits one
    batch per step. Use --ai-opponents for extra idle slots, which do not compete.

    Examples:
      nttd session start -s ses_abc123
      nttd session start --session ses_abc123 --agent-companies 1
    """
    import requests

    # Before the server is contacted. The argument is wrong whether or not anything is
    # running, and checking connectivity first reported a network problem for what is
    # actually a typo. Refused here as well as by the server so the reason is a
    # sentence rather than a validation error quoting a bound.
    if agent_companies > MAX_CONTESTANT_COMPANIES:
        console.print(
            f"[red]A session holds {MAX_CONTESTANT_COMPANIES} contestant company.[/] "
            f"Several agents playing together drive that one company, so pass "
            f"--agent-companies 1. For extra idle slots that do not compete, use "
            f"--ai-opponents."
        )
        raise typer.Exit(1)

    session_id = resolve_session(session)
    url = base_url or get_base_url()
    check_server(url)

    payload: dict = {"mode": "newgame"}
    if ai_opponents >= 0:
        payload["ai_opponents"] = ai_opponents
    if agent_companies >= 0:
        payload["agent_companies"] = agent_companies

    with console.status("Starting OpenTTD server..."):
        resp = requests.post(
            f"{url}/v1/operator/admin/sessions/{session_id}/start",
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
        f"\nAttach your runner: [cyan]nttd session attach {session_id}[/]"
    )


@session_app.command("stop")
def session_stop(
    session: Annotated[str, session_option()],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Stop a running session and archive it."""
    import requests

    session_id = resolve_session(session)
    url = base_url or get_base_url()
    check_server(url)

    resp = requests.post(f"{url}/v1/operator/admin/sessions/{session_id}/stop", timeout=15)
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

    resp = requests.get(f"{url}/v1/operator/admin/sessions", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    sessions = data.get("sessions", [])

    if not sessions:
        console.print("[dim]No sessions found.[/]")
        return

    table = Table("ID", "Name", "Status", "Game Port", "Created", "Ended", "Config")
    for s in sessions:
        status = s.get("status", "?")
        running = s.get("running", False)
        status_str = f"[green]{status}[/]" if running else f"[dim]{status}[/]"
        meta = s.get("meta", {}) or {}
        config_path = meta.get("config_path", "")
        table.add_row(
            s.get("session_id", "?"),
            s.get("name", ""),
            status_str,
            str(s.get("game_port") or ""),
            s.get("created_at", "")[:19],
            s.get("ended_at", "")[:19],
            config_path,
        )
    console.print(table)


@session_app.command("status")
def session_status(
    session: Annotated[str, session_option()],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Show detailed status for a session."""
    import requests

    session_id = resolve_session(session)
    url = base_url or get_base_url()
    check_server(url)

    resp = requests.get(f"{url}/v1/operator/admin/sessions/{session_id}", timeout=10)
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
            game_resp = requests.get(f"{url}/v1/public/sessions/{session_id}/status", timeout=5)
            if game_resp.ok:
                game = game_resp.json()
                console.print(Panel(
                    f"[bold]Date:[/]   {game.get('game_date', '?')}\n"
                    f"[bold]Paused:[/] {game.get('paused', '?')}\n"
                    f"[bold]Mode:[/]   {game.get('mode', '?')}\n"
                    f"[bold]Map:[/]    {game.get('map_width', '?')}x{game.get('map_height', '?')}",
                    title="Game State",
                ))
        except Exception:
            pass

@session_app.command("attach")
def session_attach(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Show what a runner needs to play this session.

    nttd runs no agent, so a session is only useful once a contestant's own loop can
    reach it. That needs the session id, a participant token, and the routes -- and
    the token was previously visible only in the output of `session start`, or in
    participants.json on disk.

    Examples:
      nttd session attach ses_20260804_120000_abcd1234
    """
    import requests

    url = base_url or get_base_url()
    check_server(url)

    resp = requests.get(
        f"{url}/v1/operator/admin/sessions/{session_id}/participants", timeout=10,
    )
    if not resp.ok:
        console.print(f"[red]Could not read participants for[/] {session_id}")
        console.print(f"[dim]{resp.text[:200]}[/]")
        raise typer.Exit(code=1)

    participants = resp.json().get("participants") or []
    if not participants:
        console.print(
            f"[yellow]No participant tokens for[/] {session_id}.\n"
            "The session started with no contestant company, so nothing can play it. "
            "Start it with [cyan]--agent-companies 1[/]."
        )
        raise typer.Exit(code=1)

    table = Table(title=f"Attach a runner to {session_id}")
    table.add_column("Company", justify="right")
    table.add_column("Participant token")
    for entry in participants:
        table.add_row(str(entry.get("company_id", "?")), str(entry.get("token", "")))
    console.print(table)

    token = participants[0].get("token", "")
    console.print(
        "\n[bold]Real-time play[/] -- your loop observes and acts:\n"
        f"  GET  {url}/v1/participant/sessions/{session_id}/state/full\n"
        f"  POST {url}/v1/participant/sessions/{session_id}/actions/submit\n"
        "\n[bold]Stepped play[/] -- for RL and ES, the world pauses between steps:\n"
        f"  POST {url}/v1/participant/sessions/{session_id}/step/reset\n"
        f"  POST {url}/v1/participant/sessions/{session_id}/step\n"
        f"\n  header: [cyan]X-Participant-Token: {token}[/]\n"
        "[dim]The company is derived from the token, so a company_id in the body is "
        "ignored.[/]"
    )
