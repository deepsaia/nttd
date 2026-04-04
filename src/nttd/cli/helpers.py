"""Shared helpers for CLI commands."""

from __future__ import annotations

import json
import time
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


def find_log(run: str | None, log_dir: str) -> Path | None:
    """Find the most recent JSONL log file."""
    d = Path(log_dir)
    if run:
        p = Path(run)
        return p if p.exists() else None
    files = sorted(d.glob("nttd_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def print_log_lines(lines: list[str]) -> None:
    """Pretty-print JSONL log lines."""
    type_colors = {
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
            color = type_colors.get(event_type, "white")
            ts = time.strftime("%H:%M:%S", time.localtime(r.get("t", 0)))
            detail = {k: v for k, v in r.items() if k not in ("t", "type")}
            console.print(f"[dim]{ts}[/] [{color}]{event_type:<20}[/] {detail}")
        except Exception:
            console.print(line)
