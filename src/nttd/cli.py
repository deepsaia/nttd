"""nttd interactive CLI.

Commands:
  nttd run              Start everything: server + sim + tensorboard in one command
  nttd server           Start the API server only (uvicorn)
  nttd sim              Stream live metrics from a running server
  nttd status           Show live server/game status
  nttd results          Print latest benchmark results
  nttd logs             Tail the JSONL event log
  nttd tensorboard      Launch TensorBoard against the runs/ directory
  nttd scenario         Show/load a scenario config
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="nttd",
    help="nttd — Agent-agnostic API server for OpenTTD AI simulation",
    no_args_is_help=True,
)
console = Console()

_DEFAULT_BASE_URL = os.environ.get("NTTD_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# run  (all-in-one)
# ---------------------------------------------------------------------------

@app.command()
def run(
    scenario_path: Annotated[Optional[str], typer.Option("--scenario", "-s", help="Scenario .conf path")] = None,
    savegame: Annotated[Optional[str], typer.Option("--savegame", "-g", help="Load this .sav file")] = None,
    host: Annotated[str, typer.Option("--host", help="nttd server host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="nttd server port")] = 8000,
    tb_port: Annotated[int, typer.Option("--tb-port", help="TensorBoard port")] = 6006,
    no_tensorboard: Annotated[bool, typer.Option("--no-tensorboard", help="Skip TensorBoard")] = False,
    no_openttd: Annotated[bool, typer.Option("--no-openttd", help="Skip OpenTTD (use if already running)")] = False,
    openttd_bin: Annotated[Optional[str], typer.Option("--openttd", help="Path to OpenTTD binary")] = None,
    mode: Annotated[str, typer.Option("--mode", help="heartbeat | async_realtime")] = "heartbeat",
    log_level: Annotated[str, typer.Option("--log-level")] = "info",
) -> None:
    """Start OpenTTD + nttd server + TensorBoard in one command.

    All logs stream directly to this terminal.
    Metrics are written to TensorBoard (default http://localhost:6006).

    Example:
      nttd run
      nttd run --scenario config/scenario.conf
      nttd run --savegame my_map.sav
      nttd run --no-openttd       # if OpenTTD is already running
      nttd run --no-tensorboard
    """
    import signal

    import requests

    base_url = f"http://{host}:{port}"
    procs: list[subprocess.Popen] = []

    def _shutdown(sig: int, frame: object) -> None:
        console.print("\n[yellow]Shutting down…[/]")
        for p in reversed(procs):
            p.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 1. Start OpenTTD dedicated server
    if not no_openttd:
        ottd = _start_openttd(openttd_bin, savegame)
        if ottd is not None:
            procs.append(ottd)
            _wait_port("127.0.0.1", 3977, label="OpenTTD admin port", timeout=20)
        else:
            console.print("[yellow]Could not start OpenTTD — continuing without it.[/]")

    # 2. Start nttd server — inherit stdout/stderr so all logs flow to this terminal
    env = os.environ.copy()
    env["NTTD_TENSORBOARD"] = "1"
    server_cmd = [
        sys.executable, "-m", "uvicorn", "nttd.api.app:app",
        "--host", host, "--port", str(port), "--log-level", log_level,
    ]
    procs.append(subprocess.Popen(server_cmd, env=env))
    _wait_port(host, port, label="nttd API server", timeout=15)

    # 3. Launch TensorBoard (default on)
    if not no_tensorboard:
        tb_proc = _launch_tensorboard("runs", tb_port)
        if tb_proc:
            procs.append(tb_proc)

    # 4. Load scenario + start simulation mode
    try:
        params: dict = {}
        if scenario_path:
            params["config_path"] = scenario_path
        resp = requests.post(f"{base_url}/session/scenario", params=params, timeout=10)
        cfg = resp.json() if resp.ok else {}
        requests.post(f"{base_url}/session/mode?mode={mode}", timeout=10)
    except Exception as exc:
        console.print(f"[yellow]Could not configure simulation: {exc}[/]")
        cfg = {}

    tb_url = f"http://localhost:{tb_port}" if not no_tensorboard else "(disabled)"
    console.print(Panel(
        f"[bold]API:[/]         [cyan]{base_url}[/]  ([cyan]{base_url}/docs[/])\n"
        f"[bold]TensorBoard:[/] [cyan]{tb_url}[/]\n"
        f"[bold]Scenario:[/]    {cfg.get('scenario', 'default')}   "
        f"[bold]Mode:[/] {mode}\n\n"
        + _format_end_conditions(cfg.get("end_conditions", {})),
        title="nttd running — Ctrl-C to stop",
    ))

    # 5. Block — logs stream to terminal naturally
    try:
        procs[0].wait()
    except (KeyboardInterrupt, SystemExit):
        pass

    console.print("[yellow]Shutting down…[/]")
    for p in reversed(procs):
        p.terminate()


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------

@app.command()
def server(
    host: Annotated[str, typer.Option("--host", "-h", help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload on code changes")] = False,
    tensorboard: Annotated[bool, typer.Option("--tensorboard", help="Enable TensorBoard logging")] = False,
    log_level: Annotated[str, typer.Option("--log-level", help="Uvicorn log level")] = "info",
) -> None:
    """Start the nttd API server."""
    env = os.environ.copy()
    if tensorboard:
        env["NTTD_TENSORBOARD"] = "1"
        console.print("[bold green]TensorBoard logging enabled — run: tensorboard --logdir runs/[/]")

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
        subprocess.run(cmd, env=env, check=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/]")


# ---------------------------------------------------------------------------
# sim
# ---------------------------------------------------------------------------

@app.command()
def sim(
    scenario: Annotated[Optional[str], typer.Option("--scenario", "-s", help="Path to scenario .conf")] = None,
    mode: Annotated[str, typer.Option("--mode", "-m", help="heartbeat | async_realtime")] = "heartbeat",
    steps: Annotated[int, typer.Option("--steps", help="Heartbeat steps (0=infinite)")] = 0,
    base_url: Annotated[str, typer.Option("--url", help="nttd server base URL")] = _DEFAULT_BASE_URL,
) -> None:
    """Load a scenario, start the heartbeat loop, and stream live metrics."""
    import requests

    _check_server(base_url)

    # Load scenario
    params: dict = {}
    if scenario:
        params["config_path"] = scenario
    resp = requests.post(f"{base_url}/session/scenario", params=params, timeout=10)
    if resp.status_code == 200:
        cfg = resp.json()
        console.print(Panel(
            f"[bold]{cfg['scenario']}[/]\n{cfg.get('description', '')}\n\n"
            f"Heartbeat: [cyan]{cfg['heartbeat_interval_days']} days[/]  "
            f"Action window: [cyan]{cfg['action_window_seconds']}s[/]  "
            f"Speed: [cyan]{cfg['game_speed']}x[/]\n\n"
            + _format_end_conditions(cfg.get("end_conditions", {})),
            title="Scenario loaded",
        ))
    else:
        console.print(f"[yellow]Could not load scenario: {resp.status_code}[/]")

    # Set mode
    requests.post(f"{base_url}/session/mode?mode={mode}", timeout=10)
    console.print(f"[green]Mode set: {mode}[/]")

    # Stream live metrics
    console.print("[dim]Streaming metrics (Ctrl-C to stop)…[/]\n")
    step = 0
    try:
        with Live(console=console, refresh_per_second=2) as live:
            while steps == 0 or step < steps:
                time.sleep(2.0)
                try:
                    r = requests.get(f"{base_url}/state/metrics", timeout=5)
                    bench = requests.get(f"{base_url}/benchmark/results", timeout=5)
                    table = _build_metrics_table(r.json() if r.ok else {}, bench.json() if bench.ok else {})
                    live.update(table)
                    step += 1
                except Exception:
                    live.update("[red]Waiting for server…[/]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Simulation monitor stopped.[/]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command()
def status(
    base_url: Annotated[str, typer.Option("--url", help="nttd server base URL")] = _DEFAULT_BASE_URL,
) -> None:
    """Show live game status from the running nttd server."""
    import requests

    _check_server(base_url)

    r = requests.get(f"{base_url}/health", timeout=5)
    health = r.json()
    r2 = requests.get(f"{base_url}/session/status", timeout=5)
    game = r2.json()
    r3 = requests.get(f"{base_url}/agents/list", timeout=5)
    agents = r3.json()

    rprint(Panel(
        f"[bold]OpenTTD:[/] {'[green]connected[/]' if health['openttd'] == 'connected' else '[red]disconnected[/]'}\n"
        f"[bold]Mode:[/] [cyan]{game.get('mode')}[/]  "
        f"[bold]Date:[/] {game.get('game_date')}  "
        f"[bold]Paused:[/] {game.get('paused')}  "
        f"[bold]Speed:[/] {game.get('speed')}x\n"
        f"[bold]Map:[/] {game.get('map_width')}×{game.get('map_height')}\n"
        f"[bold]Agents connected:[/] {len(agents)}",
        title="nttd status",
    ))

    if agents:
        t = Table("agent_id", "company_scope", "subscriptions")
        for a in agents:
            t.add_row(a["agent_id"], str(a.get("company_scope")), str(len(a.get("subscriptions", []))))
        console.print(t)


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

@app.command()
def results(
    base_url: Annotated[str, typer.Option("--url", help="nttd server base URL")] = _DEFAULT_BASE_URL,
    export: Annotated[Optional[str], typer.Option("--export", "-e", help="Export JSON to path")] = None,
) -> None:
    """Print the latest benchmark results."""
    import requests

    _check_server(base_url)

    r = requests.get(f"{base_url}/benchmark/results", timeout=10)
    data = r.json()

    console.print(Panel(
        f"[bold]Game days elapsed:[/] {data['game_days_elapsed']}\n"
        f"[bold]Wall time elapsed:[/] {data['wall_time_elapsed_s']}s\n"
        f"[bold]Start date:[/] {data['start_date']}  →  [bold]Current:[/] {data['current_date']}",
        title="Benchmark Results",
    ))

    t = Table("id", "name", "balance", "loan", "income", "value", "vehicles", "stations", "actions", "success%")
    for c in data.get("companies", []):
        t.add_row(
            str(c["id"]), c["name"],
            f"{c['balance']:,}", f"{c['loan']:,}", f"{c['income']:,}", f"{c['company_value']:,}",
            str(c["vehicles"]), str(c["stations"]),
            str(c["actions_submitted"]), f"{c['success_rate']*100:.0f}%",
        )
    console.print(t)

    if export:
        requests.post(f"{base_url}/benchmark/export", params={"output_path": export}, timeout=10)
        console.print(f"[green]Exported to {export}[/]")


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

@app.command()
def logs(
    run: Annotated[Optional[str], typer.Option("--run", "-r", help="Specific JSONL file to read")] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Tail the newest log file")] = False,
    log_dir: Annotated[str, typer.Option("--log-dir", help="Log directory")] = "runs",
    last: Annotated[int, typer.Option("--last", "-n", help="Show last N lines")] = 40,
) -> None:
    """Read or tail the JSONL event log."""
    log_path = _find_log(run, log_dir)
    if log_path is None:
        console.print("[red]No log file found.[/]")
        raise typer.Exit(1)

    console.print(f"[dim]Reading {log_path}[/]")

    lines = log_path.read_text().strip().splitlines()
    _print_log_lines(lines[-last:])

    if follow:
        console.print("[dim]Following (Ctrl-C to stop)…[/]")
        try:
            with log_path.open() as f:
                f.seek(0, 2)  # seek to end
                while True:
                    line = f.readline()
                    if line:
                        _print_log_lines([line.strip()])
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# tensorboard
# ---------------------------------------------------------------------------

@app.command()
def tensorboard(
    log_dir: Annotated[str, typer.Option("--log-dir", help="TensorBoard log directory")] = "runs",
    port: Annotated[int, typer.Option("--port", "-p", help="TensorBoard port")] = 6006,
) -> None:
    """Launch TensorBoard pointing at the runs/ directory.

    Requires the tensorboard package (not tensorboardX):
      uv pip install tensorboard
    """
    console.print(f"[bold]Launching TensorBoard[/] — open [cyan]http://localhost:{port}[/]")
    proc = _launch_tensorboard(log_dir, port)
    if proc is None:
        raise typer.Exit(1)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        console.print("\n[yellow]TensorBoard stopped.[/]")


# ---------------------------------------------------------------------------
# scenario
# ---------------------------------------------------------------------------

@app.command()
def scenario(
    config_path: Annotated[Optional[str], typer.Option("--config", "-c", help="Path to .conf file")] = None,
    base_url: Annotated[str, typer.Option("--url", help="nttd server base URL")] = _DEFAULT_BASE_URL,
) -> None:
    """Load and display a scenario config."""
    import requests

    _check_server(base_url)

    params: dict = {}
    if config_path:
        params["config_path"] = config_path
    resp = requests.post(f"{base_url}/session/scenario", params=params, timeout=10)
    resp.raise_for_status()
    cfg = resp.json()

    console.print(Panel(
        f"[bold]Name:[/] {cfg['scenario']}\n"
        f"[bold]Description:[/] {cfg.get('description', '—')}\n\n"
        f"[bold]Heartbeat interval:[/] {cfg['heartbeat_interval_days']} game-days\n"
        f"[bold]Action window:[/] {cfg['action_window_seconds']}s\n"
        f"[bold]Game speed:[/] {cfg['game_speed']}x\n\n"
        + _format_end_conditions(cfg.get("end_conditions", {})),
        title="Active Scenario",
    ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPENTTD_CANDIDATES = [
    "/Applications/OpenTTD.app/Contents/MacOS/openttd",  # macOS
    "openttd",                                            # Linux / in PATH
    "/usr/games/openttd",
    "/usr/bin/openttd",
]

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _find_openttd(override: str | None) -> str | None:
    """Return path to openttd binary, or None if not found."""
    if override:
        return override if Path(override).exists() else None
    for candidate in _OPENTTD_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return str(p)
        # also try which
    try:
        result = subprocess.run(["which", "openttd"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _ensure_gs_symlink() -> None:
    """Symlink the nttd GameScript into ~/Documents/OpenTTD/game/ for discovery."""
    gs_source = _PROJECT_ROOT / "ottd_config" / "game" / "nttd-gs"
    if not gs_source.exists():
        return
    gs_target = Path.home() / "Documents" / "OpenTTD" / "game" / "nttd-gs"
    gs_target.parent.mkdir(parents=True, exist_ok=True)
    if not gs_target.exists() and not gs_target.is_symlink():
        gs_target.symlink_to(gs_source)
        console.print(f"[dim]Symlinked GameScript → {gs_target}[/]")


def _start_openttd(openttd_bin: str | None, savegame: str | None) -> "subprocess.Popen | None":
    """Start OpenTTD as a dedicated server. Returns Popen or None on failure."""
    binary = _find_openttd(openttd_bin)
    if binary is None:
        console.print(
            "[yellow]OpenTTD binary not found.[/] Install OpenTTD or pass [cyan]--openttd /path/to/openttd[/]"
        )
        return None

    _ensure_gs_symlink()

    config = _PROJECT_ROOT / "ottd_config" / "openttd.cfg"
    cmd = [binary, "-D", "-c", str(config)]
    if savegame:
        cmd += ["-g", savegame]
    else:
        cmd += ["-g"]  # new game

    console.print(f"[bold]Starting OpenTTD[/]  [dim]{' '.join(cmd)}[/]")
    return subprocess.Popen(cmd)


def _wait_port(host: str, port: int, label: str, timeout: float = 15.0) -> None:
    """Block until TCP port accepts connections, or timeout."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            with socket.create_connection((host, port), timeout=1):
                console.print(f"[green]✓[/] {label} ready on {host}:{port}")
                return
        except OSError:
            pass
    console.print(f"[yellow]⚠[/] {label} on {host}:{port} not ready after {timeout:.0f}s — continuing anyway")


def _launch_tensorboard(log_dir: str, port: int) -> "subprocess.Popen | None":
    """Start tensorboard as a background process. Returns the Popen object or None on failure."""
    try:
        proc = subprocess.Popen(
            ["tensorboard", "--logdir", log_dir, "--port", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return proc
    except FileNotFoundError:
        console.print(
            "[yellow]tensorboard not found.[/] TensorboardX writes event files but you need the "
            "tensorboard viewer separately:\n  [cyan]uv pip install tensorboard[/]"
        )
        return None


def _check_server(base_url: str) -> None:
    import requests
    try:
        requests.get(f"{base_url}/health", timeout=3)
    except Exception:
        console.print(f"[red]Cannot reach nttd server at {base_url}[/]")
        console.print("[dim]Start it with: nttd server[/]")
        raise typer.Exit(1)


def _format_end_conditions(ec: dict) -> str:
    parts = [f"[bold]End conditions[/] (logic=[cyan]{ec.get('logic', '?')}[/]):"]
    for key, cfg in ec.items():
        if key == "logic" or not isinstance(cfg, dict):
            continue
        if cfg.get("enabled"):
            detail = ", ".join(f"{k}={v}" for k, v in cfg.items() if k != "enabled")
            parts.append(f"  [green]✓[/] {key}: {detail}")
        else:
            parts.append(f"  [dim]✗ {key}[/]")
    return "\n".join(parts)


def _build_metrics_table(metrics: dict, bench: dict) -> Table:
    t = Table(title=f"Live Metrics  (step {metrics.get('step', '—')}, date={metrics.get('game_date', '—')})")
    t.add_column("Company")
    t.add_column("Balance", justify="right")
    t.add_column("Income", justify="right")
    t.add_column("Vehicles", justify="right")
    t.add_column("Stations", justify="right")
    t.add_column("Actions", justify="right")
    t.add_column("Success%", justify="right")

    bench_by_id = {c["id"]: c for c in bench.get("companies", [])}

    for cid, c in metrics.get("companies", {}).items():
        b = bench_by_id.get(int(cid), {})
        t.add_row(
            f"[bold]{c.get('name', cid)}[/]",
            f"{c.get('money', 0):,}",
            f"{c.get('income', 0):,}",
            str(c.get("vehicles", 0)),
            str(c.get("stations", 0)),
            str(b.get("actions_submitted", "—")),
            f"{b.get('success_rate', 0)*100:.0f}%" if "success_rate" in b else "—",
        )
    return t


def _find_log(run: str | None, log_dir: str) -> Path | None:
    d = Path(log_dir)
    if run:
        p = Path(run)
        return p if p.exists() else None
    files = sorted(d.glob("nttd_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _print_log_lines(lines: list[str]) -> None:
    _TYPE_COLORS = {
        "observation": "blue",
        "action_submitted": "cyan",
        "action_result": "green",
        "gs_command": "magenta",
        "error": "red",
        "reconnect": "yellow",
    }
    for line in lines:
        if not line:
            continue
        try:
            r = json.loads(line)
            event_type = r.get("type", "?")
            color = _TYPE_COLORS.get(event_type, "white")
            ts = time.strftime("%H:%M:%S", time.localtime(r.get("t", 0)))
            detail = {k: v for k, v in r.items() if k not in ("t", "type")}
            console.print(f"[dim]{ts}[/] [{color}]{event_type:<20}[/] {detail}")
        except Exception:
            console.print(line)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
