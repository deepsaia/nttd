"""Shared helpers for CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console

if TYPE_CHECKING:
    from nttd.config.scenario_config import EndConditionsConfig

console = Console()

_DEFAULT_BASE_URL = "http://localhost:8000"


def get_base_url() -> str:
    """Return the nttd base URL from env or default."""
    import os

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


def load_instructions(path: str) -> str:
    """Load agent instructions from a file or a python_file:function_name reference.

    Supports:
      - Plain text file: "prompts/bus.txt"
      - Python callable: "examples/agent_instructions.py:get_bus_agent_prompt"
    """
    if ":" in path and not path.endswith(")"):
        file_part, func_name = path.rsplit(":", 1)
        file_path = Path(file_part)
        if file_path.suffix == ".py" and file_path.exists():
            import importlib.util

            spec = importlib.util.spec_from_file_location("_instructions", str(file_path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                func = getattr(mod, func_name, None)
                if callable(func):
                    result = func()
                    return result if isinstance(result, str) else str(result)

    file_path = Path(path)
    if file_path.exists():
        return file_path.read_text()

    return path  # treat as inline instructions string


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
        parts.append(f"heartbeats={ec.max_heartbeats.count}")
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
    from nttd.analysis.loader import SESSIONS_DIR

    p = Path(value)
    if "/" in value or p.is_dir():
        resolved = p.resolve()
        return resolved.name, resolved
    return value, SESSIONS_DIR / value


def complete_session(incomplete: str) -> list[str]:
    """Shell autocompletion for session IDs.

    Scans logs/sessions/ for directories matching the incomplete prefix.
    """
    import os

    sessions_dir = Path(os.environ.get("NTTD_SESSIONS_DIR", "logs/sessions"))
    if not sessions_dir.is_dir():
        return []
    return [
        d.name for d in sorted(sessions_dir.iterdir())
        if d.is_dir() and d.name.startswith(incomplete)
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
    """Build the end conditions REST payload from config."""
    payload: dict = {"logic": ec.logic}
    if ec.time_limit.enabled:
        payload["wall_minutes"] = ec.time_limit.wall_minutes
    if ec.game_date_limit.enabled:
        payload["end_year"] = ec.game_date_limit.end_year
    if ec.revenue_threshold.enabled:
        payload["revenue_threshold"] = ec.revenue_threshold.total_revenue
    if ec.cargo_threshold.enabled:
        payload["cargo_threshold"] = ec.cargo_threshold.total_cargo_delivered
    return payload


