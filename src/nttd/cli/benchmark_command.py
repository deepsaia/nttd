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
    load_instructions,
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


def _parse_agents(raw: Any) -> list[dict[str, Any]]:
    """Parse agent definitions from the raw ConfigTree into dicts."""
    agents_raw = _get_raw(raw, "agents", [])
    if not agents_raw:
        return []

    agents: list[dict[str, Any]] = []
    for a in agents_raw:
        agent_dict: dict[str, Any] = {
            "agent_id": a.get("agent_id", "agent"),
            "company_id": int(a.get("company_id", 0)),
            "nttd_framework": a.get("nttd_framework", "openai"),
            "model": a.get("model", "gpt-4o"),
            "agent_type": a.get("agent_type", "road"),
            "instructions": a.get("instructions", ""),
            "instructions_file": a.get("instructions_file", ""),
            "observation_mode": a.get("observation_mode") or a.get("snapshot_class") or "compact",
            "include_finance": bool(a.get("include_finance", False)),
            "poll_interval": float(a.get("poll_interval", 5.0)),
            "observation_tools": bool(a.get("observation_tools", True)),
            "max_actions_per_cycle": int(a.get("max_actions_per_cycle", 10)),
            "max_history_cycles": int(a.get("max_history_cycles", 10)),
            "api_key_env": a.get("api_key_env", "OPENAI_API_KEY"),
        }
        mas_transport = a.get("mas_transport", None)
        if mas_transport:
            agent_dict["mas_transport"] = {
                "protocol": mas_transport.get("protocol", "custom"),
                "mas_framework": mas_transport.get("mas_framework", "generic"),
                "endpoint": mas_transport.get("endpoint", ""),
                "stream_endpoint": mas_transport.get("stream_endpoint", ""),
                "config_path": mas_transport.get("config_path", ""),
                "timeout": float(mas_transport.get("timeout", 60.0)),
                "retry_count": int(mas_transport.get("retry_count", 2)),
                "retry_backoff": float(mas_transport.get("retry_backoff", 1.0)),
            }
            auth = mas_transport.get("auth", None)
            if auth:
                agent_dict["mas_transport"]["auth"] = {
                    "type": auth.get("type", "none"),
                    "token_env": auth.get("token_env", ""),
                }
        mas_config = a.get("mas_config", None)
        if mas_config and "mas_transport" not in agent_dict:
            agent_dict["mas_config"] = mas_config
        agents.append(agent_dict)
    return agents


def benchmark(
    config: Annotated[str, typer.Option("--config", "-c", help="Path to HOCON scenario config")],
    speed: Annotated[int, typer.Option("--speed", help="Override game speed")] = -1,
    ai_opponents: Annotated[int, typer.Option("--ai-opponents", help="Override AI opponent count")] = -1,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output directory for results")] = None,
    base_url: Annotated[str, typer.Option("--url", help="nttd server URL")] = "",
) -> None:
    """Run a full benchmark from HOCON config.

    Creates a session, starts OpenTTD, registers agents from config,
    starts all agent loops, waits for end condition, and exports results.

    Examples:
      nttd benchmark --config config/scenario.conf
      nttd benchmark --config config/scenario.conf --speed 3 --output results/
    """
    import requests

    from nttd.config.scenario_config import load as load_scenario
    from nttd.config.scenario_config import scenario_to_settings

    url = base_url or get_base_url()
    check_server(url)

    # 1. Load config
    cfg = load_scenario(config)
    if speed >= 0:
        cfg.runtime.game_speed = speed
    settings = scenario_to_settings(cfg)

    # Read display values from flattened settings (same pattern as session create)
    map_x = 2 ** int(settings.get("game_creation.map_x", "8"))
    map_y = 2 ** int(settings.get("game_creation.map_y", "8"))
    ai_count = ai_opponents if ai_opponents >= 0 else int(settings.get("difficulty.max_no_competitors", "0"))

    # Parse agents from raw ConfigTree
    raw = cfg._raw or {}
    agents_list = _parse_agents(raw)

    console.print(Panel(
        f"[bold]Config:[/]       {config}\n"
        f"[bold]Map:[/]          {map_x}x{map_y}\n"
        f"[bold]Speed:[/]        {cfg.runtime.game_speed}x\n"
        f"[bold]AI opponents:[/] {ai_count}\n"
        f"[bold]Agents:[/]       {len(agents_list)}\n"
        + format_end_conditions_brief(cfg.end_conditions),
        title="Benchmark configuration",
    ))

    # 2. Create session
    resp = requests.post(
        f"{url}/admin/sessions/new",
        json={"name": f"benchmark_{cfg.name}", "settings": settings},
        timeout=10,
    )
    resp.raise_for_status()
    session_id = resp.json()["session_id"]
    console.print(f"[green]Created session:[/] [cyan]{session_id}[/]")

    # 3. Set end conditions
    ec_payload = build_end_conditions_payload(cfg.end_conditions)
    if len(ec_payload) > 1:
        requests.post(
            f"{url}/admin/sessions/{session_id}/end-conditions",
            json=ec_payload,
            timeout=10,
        )

    # 4. Start session (spawn OpenTTD)
    with console.status("Starting OpenTTD server..."):
        resp = requests.post(
            f"{url}/admin/sessions/{session_id}/start",
            json={
                "mode": "newgame",
                "ai_opponents": ai_count,
                "agent_companies": len({a["company_id"] for a in agents_list}),
            },
            timeout=120,
        )
    resp.raise_for_status()
    start_data = resp.json()
    console.print(
        f"[green]Server started:[/] game_port=[cyan]{start_data.get('game_port')}[/] "
        f"pid={start_data.get('pid')}"
    )

    # 5. Set game speed
    if cfg.runtime.game_speed > 1:
        requests.post(
            f"{url}/sessions/{session_id}/speed",
            params={"speed": cfg.runtime.game_speed},
            timeout=5,
        )

    # 6. Set runtime mode
    requests.post(
        f"{url}/sessions/{session_id}/mode",
        params={"mode": cfg.runtime.mode},
        timeout=5,
    )

    # 7. Register and start agents from config
    for agent_cfg in agents_list:
        agent_instructions = agent_cfg["instructions"]
        if agent_cfg["instructions_file"]:
            agent_instructions = load_instructions(agent_cfg["instructions_file"])

        agent_payload: dict[str, Any] = {
            "agent_id": agent_cfg["agent_id"],
            "company_id": agent_cfg["company_id"],
            "nttd_framework": agent_cfg["nttd_framework"],
            "model": agent_cfg["model"],
            "agent_type": agent_cfg["agent_type"],
            "instructions": agent_instructions,
            "observation_mode": agent_cfg["observation_mode"],
            "include_finance": agent_cfg["include_finance"],
            "poll_interval": agent_cfg["poll_interval"],
            "observation_tools": agent_cfg["observation_tools"],
            "max_actions_per_cycle": agent_cfg["max_actions_per_cycle"],
            "max_history_cycles": agent_cfg["max_history_cycles"],
            "api_key_env": agent_cfg["api_key_env"],
        }
        if "mas_transport" in agent_cfg:
            agent_payload["mas_transport"] = agent_cfg["mas_transport"]
        if "mas_config" in agent_cfg:
            agent_payload["mas_config"] = agent_cfg["mas_config"]
        resp = requests.post(
            f"{url}/sessions/{session_id}/gameloop/agents/register",
            json=agent_payload,
            timeout=10,
        )
        if resp.ok:
            console.print(
                f"  [green]Registered:[/] {agent_cfg['agent_id']} "
                f"(company {agent_cfg['company_id']}, {agent_cfg['model']})"
            )
        else:
            console.print(f"  [red]Failed to register {agent_cfg['agent_id']}:[/] {resp.text}")
            continue

        resp = requests.post(
            f"{url}/sessions/{session_id}/gameloop/agents/{agent_cfg['agent_id']}/start",
            timeout=10,
        )
        if resp.ok:
            console.print(f"  [green]Started:[/]    {agent_cfg['agent_id']}")
        else:
            console.print(f"  [red]Failed to start {agent_cfg['agent_id']}:[/] {resp.text}")

    # 8. Monitor until end condition
    console.print("\n[bold]Benchmark running[/] -- waiting for end condition...")
    console.print("[dim]Press Ctrl+C to stop early[/]\n")

    try:
        _monitor_loop(url, session_id)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted -- stopping session...[/]")

    # 9. Export results
    _export_results(url, session_id, output)

    # 10. Stop session
    requests.post(f"{url}/admin/sessions/{session_id}/stop", timeout=15)
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
                resp = requests.get(f"{base_url}/admin/sessions/{session_id}", timeout=5)
                if not resp.ok:
                    live.update("[red]Lost connection to server[/]")
                    break

                session_data = resp.json()
                status = session_data.get("status", "?")
                if status in ("ended", "archived"):
                    live.update(f"[green]Session ended:[/] {session_data.get('end_reason', 'completed')}")
                    break

                game_resp = requests.get(f"{base_url}/sessions/{session_id}/status", timeout=5)
                game = game_resp.json() if game_resp.ok else {}

                table = Table(title=f"Benchmark -- cycle {cycle}")
                table.add_column("Metric")
                table.add_column("Value")
                table.add_row("Session", session_id)
                table.add_row("Status", f"[green]{status}[/]")
                table.add_row("Game date", str(game.get("game_date", "?")))
                table.add_row("Paused", str(game.get("paused", "?")))
                table.add_row("Speed", f"{game.get('speed', '?')}x")
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
        resp = requests.get(f"{base_url}/sessions/{session_id}/benchmark/results", timeout=10)
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
