"""Shared helpers for CLI commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

from nttd.store import session_paths

if TYPE_CHECKING:
    from nttd.config.scenario_config import EndConditionsConfig

console = Console()

_DEFAULT_BASE_URL = "http://localhost:8000"


def load_dotenv(env_file: Path | None = None) -> dict[str, str]:
    """Load key=value pairs from a .env file, skipping comments and blanks.

    If env_file is None, defaults to .env in the current directory.
    Returns the loaded vars (empty dict if file not found).
    """
    path = env_file or Path(".env")
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        loaded[key] = value
    return loaded


def apply_dotenv(env_file: Path | None = None) -> dict[str, str]:
    """Load .env and inject into os.environ (existing vars take precedence)."""
    loaded = load_dotenv(env_file)
    for key, value in loaded.items():
        if key not in os.environ:
            os.environ[key] = value
    return loaded


def get_base_url() -> str:
    """Return the nttd base URL from env or default."""
    return os.environ.get("NTTD_BASE_URL", _DEFAULT_BASE_URL)


def check_server(base_url: str) -> None:
    """Verify the nttd server is reachable."""
    import requests

    try:
        requests.get(f"{base_url}/health", timeout=3)
    except Exception:
        console.print(f"[red]Cannot reach nttd server at {base_url}[/]")
        console.print("[dim]Start it with: nttd server[/]")
        raise typer.Exit(1)



def format_end_conditions_brief(ec: EndConditionsConfig) -> str:
    """Format end conditions as a brief summary string."""
    parts: list[str] = []
    if ec.time_limit.enabled:
        parts.append(f"time={ec.time_limit.wall_minutes}min")
    if ec.game_date_limit.enabled:
        parts.append(f"date={ec.game_date_limit.end_year}")
    if ec.revenue_threshold.enabled:
        parts.append(f"revenue={ec.revenue_threshold.total_revenue:,}")
    if ec.cargo_threshold.enabled:
        parts.append(f"cargo={ec.cargo_threshold.total_cargo_delivered:,}")
    if ec.max_heartbeats.enabled:
        parts.append(f"steps={ec.max_heartbeats.count}")
    if ec.bankruptcy.enabled:
        parts.append("bankruptcy")
    if not parts:
        return "[bold]End:[/]         [dim]none configured[/]"
    return f"[bold]End:[/]         {', '.join(parts)} (logic={ec.logic})"


def resolve_session(value: str) -> str:
    """Resolve a session identifier to a session ID.

    Accepts either a plain session ID (e.g. ``ses_abc123``) or a
    relative/absolute path to a session directory (e.g.
    ``logs/sessions/ses_abc123`` or ``/abs/path/ses_abc123``).

    Returns the session ID string (directory basename).
    """
    p = Path(value)
    if "/" in value or p.is_dir():
        return p.resolve().name
    return value


def resolve_session_path(value: str) -> tuple[str, Path]:
    """Resolve a session identifier to (session_id, session_dir).

    Like :func:`resolve_session`, but also returns the resolved directory
    path for commands that operate on the filesystem (e.g. ``nttd analyze``).
    """
    p = Path(value)
    if "/" in value or p.is_dir():
        resolved = p.resolve()
        return resolved.name, resolved
    return value, session_paths.session_dir(value)


def complete_session(incomplete: str) -> list[str]:
    """Shell autocompletion for session IDs.

    Scans logs/sessions/ for directories matching the incomplete prefix.
    """
    return [
        d.name for d in session_paths.iter_session_dirs()
        if d.name.startswith(incomplete)
    ]


def complete_reports(incomplete: str) -> list[str]:
    """Shell autocompletion for report names."""
    from nttd.analysis.reports.registry import ensure_reports_loaded, list_reports

    try:
        ensure_reports_loaded()
        return [r for r in list_reports() if r.startswith(incomplete)]
    except Exception:
        return []


def session_option() -> typer.Option:
    """Reusable typer.Option for --session/-s with autocompletion."""
    return typer.Option(
        "--session", "-s",
        help="Session ID or path",
        autocompletion=complete_session,
    )


def build_end_conditions_payload(ec: EndConditionsConfig) -> dict:
    """Build the end conditions REST payload from config.

    Every enabled condition must appear here or it silently never reaches the
    server -- which is how max_heartbeats, the natural bound for stepped mode,
    came to be unreachable end to end.
    """
    payload: dict = {"logic": ec.logic}
    if ec.time_limit.enabled:
        payload["wall_minutes"] = ec.time_limit.wall_minutes
    if ec.game_date_limit.enabled:
        payload["end_year"] = ec.game_date_limit.end_year
    if ec.revenue_threshold.enabled:
        payload["revenue_threshold"] = ec.revenue_threshold.total_revenue
    if ec.cargo_threshold.enabled:
        payload["cargo_threshold"] = ec.cargo_threshold.total_cargo_delivered
    if ec.max_heartbeats.enabled:
        payload["max_heartbeats"] = ec.max_heartbeats.count
    if ec.bankruptcy.enabled:
        payload["bankruptcy"] = True
    return payload


