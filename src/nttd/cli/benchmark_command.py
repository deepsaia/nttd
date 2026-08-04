"""nttd benchmark command -- run a full benchmark from HOCON config."""

import json
import time
from pathlib import Path
from typing import Annotated, Any, Optional

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


def _get_raw(cfg: Any, path: str, default: Any = None) -> Any:
    """Safely traverse a pyhocon ConfigTree by dot-path."""
    try:
        parts = path.split(".")
        node = cfg
        for part in parts:
            node = node[part]
        return node
    except Exception:
        return default


def _print_attach_instructions(
    url: str, session_id: str, participants: list[dict[str, Any]],
) -> None:
    """Show a contestant how to attach its own loop to this session.

    nttd runs no agent, so a benchmark is only useful if the operator can see the
    session id and the per-company token. The token is addressing rather than a
    secret: it answers "which company is this action for" in a form the caller
    cannot lie about.
    """
    if not participants:
        console.print(
            "[yellow]No participant tokens issued.[/] The session started with no "
            "contestant company, so nothing can play it."
        )
        return

    table = Table(title="Attach your runner")
    table.add_column("Company", justify="right")
    table.add_column("Participant token")
    for entry in participants:
        table.add_row(str(entry.get("company_id", "?")), str(entry.get("token", "")))
    console.print(table)

    first = participants[0]
    console.print(
        "\n[bold]Your loop observes and acts over these routes:[/]\n"
        f"  GET  {url}/v1/participant/sessions/{session_id}/state/full\n"
        f"  POST {url}/v1/participant/sessions/{session_id}/actions/submit\n"
        f"  header: X-Participant-Token: {first.get('token', '')}\n"
        "[dim]The company is derived from the token, so a company_id in the body is "
        "ignored.[/]\n"
    )


def benchmark(
    config: Annotated[str, typer.Option("--config", "-c", help="Path to HOCON scenario config")],
    seed: Annotated[int, typer.Option("--seed", help="Override map generation seed")] = -1,
    ai_opponents: Annotated[int, typer.Option("--ai-opponents", help="Override AI opponent count")] = -1,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output directory for results")] = None,
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Stand up a benchmark task and wait for it to end.

    Creates the session, starts OpenTTD on the scenario's world, prints the
    participant token a contestant needs, then waits for an end condition and writes
    the result record.

    It does NOT run an agent. The contestant owns the observe/decide/act loop and
    connects over the participant REST routes -- an LLM agent, a multi-agent system,
    an RL policy, or an ES candidate, all through the same surface. Attach yours to
    the printed session id and token while this waits.

    Config validation is strict: an ill-specified scenario is refused rather than
    silently run with substituted defaults.

    Examples:
      nttd benchmark --config config/benchmark/t2_example.conf
      nttd benchmark --config config/benchmark/t2_example.conf --seed 2002
    """
    import requests

    from nttd.config.scenario_config import ScenarioConfigError, scenario_to_settings
    from nttd.config.scenario_config import load as load_scenario

    url = base_url or get_base_url()
    check_server(url)

    # 1. Load config.
    #
    # Benchmarks are scored runs, so validation is strict: an ill-specified
    # scenario is refused rather than silently substituted with defaults. A typo
    # must not quietly produce a run on a different world than the one claimed.
    cfg = load_scenario(config)
    try:
        settings = scenario_to_settings(cfg, strict=True)
    except ScenarioConfigError as exc:
        console.print(f"[red]Invalid scenario config:[/] {config}")
        for problem in str(exc).split("; "):
            console.print(f"  [red]-[/] {problem}")
        raise typer.Exit(code=1) from exc

    # --seed overrides the scenario. Both keys must be set: the cfg key is the
    # record, while _map_seed is what reaches OpenTTD's -G flag and actually pins
    # generation.
    if seed >= 0:
        settings["game_creation.generation_seed"] = str(seed)
        settings["_map_seed"] = str(seed)

    # Read display values from flattened settings (same pattern as session create)
    map_x = 2 ** int(settings.get("game_creation.map_x", "8"))
    map_y = 2 ** int(settings.get("game_creation.map_y", "8"))
    ai_count = ai_opponents if ai_opponents >= 0 else int(settings.get("difficulty.max_no_competitors", "0"))
    effective_seed = settings.get("_map_seed")

    # One company per contestant. Multi-agent entries share a company, because
    # scoring is per company and the runner decides how many loops attach to it.
    agent_companies = 1

    if not effective_seed:
        console.print(
            "[yellow]No map seed set:[/] this run is not reproducible and cannot be "
            "compared against other runs. Set map.seed in the config or pass --seed."
        )

    console.print(Panel(
        f"[bold]Config:[/]       {config}\n"
        f"[bold]Map:[/]          {map_x}x{map_y}\n"
        f"[bold]Seed:[/]         "
        + (f"[cyan]{effective_seed}[/]" if effective_seed else "[yellow]random[/]") + "\n"
        f"[bold]AI opponents:[/] {ai_count}\n"
        + format_end_conditions_brief(cfg.end_conditions),
        title="Benchmark configuration",
    ))

    # 2. Create session.
    #
    # config_path only: the server loads the scenario itself. Sending the whole
    # settings dict is refused, because it carries _scored and _fair_* which a client
    # may not supply -- they decide whether the run is scored and what bounds it.
    #
    # --seed is the one thing a caller may still override, since which world to play
    # is the caller's choice while whether it is scored is not.
    overrides: dict[str, str] = {}
    if seed >= 0:
        overrides["game_creation.generation_seed"] = str(seed)
        overrides["_map_seed"] = str(seed)
    resp = requests.post(
        f"{url}/v1/operator/admin/sessions/new",
        json={
            "name": f"benchmark_{cfg.name}",
            "settings": overrides,
            "config_path": config,
        },
        timeout=10,
    )
    resp.raise_for_status()
    session_id = resp.json()["session_id"]
    console.print(f"[green]Created session:[/] [cyan]{session_id}[/]")

    # 3. Start session (spawn OpenTTD)
    with console.status("Starting OpenTTD server..."):
        resp = requests.post(
            f"{url}/v1/operator/admin/sessions/{session_id}/start",
            json={
                "mode": "newgame",
                "ai_opponents": ai_count,
                "agent_companies": agent_companies,
            },
            timeout=120,
        )
    resp.raise_for_status()
    start_data = resp.json()
    console.print(
        f"[green]Server started:[/] game_port=[cyan]{start_data.get('game_port')}[/] "
        f"pid={start_data.get('pid')}"
    )

    # The contestant's loop runs elsewhere, so print what it needs to attach.
    # Without this the token exists only in participants.json, which is a
    # discoverability problem rather than a security one -- the file sits beside the
    # runner anyway.
    _print_attach_instructions(url, session_id, start_data.get("participants") or [])

    # 4. Set end conditions (must be after start -- runtime must exist)
    ec_payload = build_end_conditions_payload(cfg.end_conditions)
    if len(ec_payload) > 1:
        resp = requests.post(
            f"{url}/v1/operator/admin/sessions/{session_id}/end-conditions",
            json=ec_payload,
            timeout=10,
        )
        resp.raise_for_status()

    # 5. A scenario may still carry runtime.game_speed from before it was known
    #    that OpenTTD has no such setting. Say so rather than appear to honour it.
    if cfg.runtime.game_speed > 1:
        console.print(
            f"[yellow]Ignoring runtime.game_speed = {cfg.runtime.game_speed}:[/] OpenTTD 15.3 "
            "has no speed control. The economy clock is fixed at 1 wall-minute per economy "
            "month, so session length is set by the end conditions alone."
        )

    # 6. Set runtime mode
    requests.post(
        f"{url}/v1/operator/sessions/{session_id}/mode",
        params={"mode": cfg.runtime.mode},
        timeout=5,
    )

    # 7. Monitor until end condition
    console.print("\n[bold]Benchmark running[/] -- waiting for end condition...")
    console.print("[dim]Press Ctrl+C to stop early[/]\n")

    try:
        _monitor_loop(url, session_id)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted -- stopping session...[/]")

    # 9. Export results
    _export_results(url, session_id, output)

    # 10. Stop session
    requests.post(f"{url}/v1/operator/admin/sessions/{session_id}/stop", timeout=15)
    console.print(f"\n[green]Benchmark complete.[/] Session {session_id} archived.")


def _monitor_loop(base_url: str, session_id: str) -> None:
    """Poll session status until it ends or is interrupted."""
    import requests
    from rich.live import Live

    cycle = 0
    with Live(console=console, refresh_per_second=1) as live:
        while True:
            time.sleep(3.0)
            try:
                resp = requests.get(f"{base_url}/v1/operator/admin/sessions/{session_id}", timeout=5)
                if not resp.ok:
                    live.update("[red]Lost connection to server[/]")
                    break

                session_data = resp.json()
                status = session_data.get("status", "?")
                if status in ("ended", "archived"):
                    live.update(f"[green]Session ended:[/] {session_data.get('end_reason', 'completed')}")
                    break

                game_resp = requests.get(f"{base_url}/v1/public/sessions/{session_id}/status", timeout=5)
                game = game_resp.json() if game_resp.ok else {}

                table = Table(title=f"Benchmark -- cycle {cycle}")
                table.add_column("Metric")
                table.add_column("Value")
                table.add_row("Session", session_id)
                table.add_row("Status", f"[green]{status}[/]")
                table.add_row("Game date", str(game.get("game_date", "?")))
                table.add_row("Paused", str(game.get("paused", "?")))
                live.update(table)
                cycle += 1

            except requests.ConnectionError:
                live.update("[red]Server unreachable[/]")
                break
            except Exception as exc:
                live.update(f"[red]Error: {exc}[/]")


def _export_results(base_url: str, session_id: str, output_dir: str | None) -> None:
    """Fetch and display benchmark results, optionally export to file."""
    import requests

    try:
        resp = requests.get(f"{base_url}/v1/operator/sessions/{session_id}/benchmark/results", timeout=10)
        if not resp.ok:
            console.print("[yellow]Could not fetch benchmark results[/]")
            return

        data = resp.json()
        table = Table(title="Results")
        table.add_column("Company")
        table.add_column("Balance", justify="right")
        table.add_column("Income", justify="right")
        table.add_column("Vehicles", justify="right")
        table.add_column("Stations", justify="right")
        table.add_column("Actions", justify="right")
        table.add_column("Success%", justify="right")

        for c in data.get("companies", []):
            table.add_row(
                c.get("name", str(c.get("id", "?"))),
                f"{c.get('balance', 0):,}",
                f"{c.get('income', 0):,}",
                str(c.get("vehicles", 0)),
                str(c.get("stations", 0)),
                str(c.get("actions_submitted", 0)),
                f"{c.get('success_rate', 0) * 100:.0f}%",
            )
        console.print(table)

        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            result_file = out_path / f"{session_id}_results.json"
            result_file.write_text(json.dumps(data, indent=2))
            console.print(f"[green]Results exported to {result_file}[/]")

    except Exception as exc:
        console.print(f"[yellow]Could not export results: {exc}[/]")

    _show_scored_result(session_id)


def _show_scored_result(session_id: str) -> None:
    """Display the scored, provenanced result record written at session end.

    This is the artifact a leaderboard ingests, so surfacing it here lets an
    operator see the actual score and confirm the run is traceable.
    """
    import os

    from nttd.db.result_writer import read_result

    sessions_dir = Path(os.environ.get("NTTD_SESSIONS_DIR", "logs/sessions"))
    rows = read_result(sessions_dir / session_id)
    if not rows:
        console.print(
            "[yellow]No result record found.[/] It is written when the session stops -- "
            "run [cyan]nttd session stop[/] if the session is still active."
        )
        return

    first = rows[0]
    table = Table(title=f"Scored result ({first['score_version']})")
    table.add_column("Rank", justify="right")
    table.add_column("Company")
    table.add_column("Score", justify="right")
    table.add_column("Cargo", justify="right")
    table.add_column("Value", justify="right")
    table.add_column("Model")
    table.add_column("Cost", justify="right")

    for rank, row in enumerate(rows, 1):
        score = str(row["primary_score"])
        if not row["rating_available"]:
            score = "[yellow]unrated[/]"
        table.add_row(
            str(rank),
            row["company_name"] or str(row["company_id"]),
            score,
            f"{row['tiebreak_cargo']:,}",
            f"{row['company_value']:,}",
            row["model"] or "-",
            f"${row['total_cost_usd']:.2f}" if row["total_cost_usd"] else "-",
        )
    console.print(table)

    seed = first["map_seed"]
    dirty = " [yellow](uncommitted changes)[/]" if first["nttd_git_dirty"] else ""
    console.print(
        f"[bold]task_id:[/] {first['task_id'] or '[yellow]none[/]'}  "
        f"[bold]seed:[/] {seed if seed >= 0 else '[yellow]random[/]'}  "
        f"[bold]nttd:[/] {first['nttd_git_sha'] or '?'}{dirty}\n"
        f"[bold]end reason:[/] {first['end_reason']}  "
        f"[bold]game days:[/] {first['game_days']}  "
        f"[bold]wall:[/] {first['wall_seconds']:.0f}s"
    )
