"""Live metrics of one session, read from its parquet files.

Two tables for a monitor that polls while the game runs: the company's finances per
game day, from the snapshot columns, and the commands per game day, from the action
log. Neither parses the snapshot JSON, so one poll costs little. Both read merged files
or the fragments of a session still in progress.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from nttd.analysis.date_utils import game_date_to_ymd
from nttd.store import parquet_reader
from nttd.store.recorder import SOURCE_API

FINANCE_COLUMNS = [
    "game_date", "tick", "captured_at",
    "c0_balance", "c0_loan", "c0_value", "num_vehicles", "num_stations",
]
ACTION_COLUMNS = ["agent_id", "game_date", "status", "source"]
# How a command's status is counted. Anything else counts as unknown.
OUTCOMES = {
    "success": "successful",
    "failed": "failed",
    "rejected": "failed",
    "blocked": "failed",
    "partial": "partial",
}


def iso_date(game_date: int) -> str:
    """The game date as YYYY-MM-DD."""
    year, month, day = game_date_to_ymd(game_date)
    return f"{year:04d}-{month:02d}-{day:02d}"


def finance_rows(session_id: str, sessions_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Company 0's finances per game day, one row per day, the latest snapshot of the day.

    Each row: game_date, date, tick, captured_at, cash, loan, net_cash, company_value,
    vehicles, stations. net_cash is cash minus loan.
    """
    table = parquet_reader.read_table(session_id, "snapshots", FINANCE_COLUMNS, sessions_dir)
    if table is None:
        return []
    latest_by_day: dict[int, dict[str, Any]] = {}
    for row in table.to_pylist():
        day = row.get("game_date")
        if day is None:
            continue
        previous = latest_by_day.get(day)
        if previous is None or (row.get("tick") or 0) >= (previous.get("tick") or 0):
            latest_by_day[day] = row
    rows = []
    for day in sorted(latest_by_day):
        row = latest_by_day[day]
        cash, loan = row.get("c0_balance"), row.get("c0_loan")
        captured = row.get("captured_at")
        rows.append({
            "game_date": day,
            "date": iso_date(day),
            "tick": row.get("tick"),
            "captured_at": captured.isoformat() if captured is not None else None,
            "cash": cash,
            "loan": loan,
            "net_cash": cash - loan if cash is not None and loan is not None else None,
            "company_value": row.get("c0_value"),
            "vehicles": row.get("num_vehicles"),
            "stations": row.get("num_stations"),
        })
    return rows


def command_rows(session_id: str, sessions_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Commands sent through the API per game day.

    Each row: game_date, date, commands, actors, successful, failed, partial, unknown.
    actors counts the distinct agent ids of the day; commands without an agent id count
    as one actor together.
    """
    table = parquet_reader.read_table(session_id, "actions", ACTION_COLUMNS, sessions_dir)
    if table is None:
        return []
    counts: dict[int, Counter] = {}
    actors: dict[int, set[str]] = {}
    for row in table.to_pylist():
        day = row.get("game_date")
        if day is None or row.get("source") != SOURCE_API:
            continue
        day_counts = counts.setdefault(day, Counter())
        day_counts["commands"] += 1
        day_counts[OUTCOMES.get(str(row.get("status")), "unknown")] += 1
        actors.setdefault(day, set()).add(row.get("agent_id") or "")
    return [
        {
            "game_date": day,
            "date": iso_date(day),
            "commands": counts[day]["commands"],
            "actors": len(actors[day]),
            "successful": counts[day]["successful"],
            "failed": counts[day]["failed"],
            "partial": counts[day]["partial"],
            "unknown": counts[day]["unknown"],
        }
        for day in sorted(counts)
    ]


def live_metrics(session_id: str, sessions_dir: Path | str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Both tables in one call."""
    return {
        "finances": finance_rows(session_id, sessions_dir),
        "commands": command_rows(session_id, sessions_dir),
    }
