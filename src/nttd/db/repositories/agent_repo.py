"""Repository for agent connection and cycle queries -- reads from conf + Parquet."""

import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from nttd.db.conf_writer import read_agents_conf

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path("logs/sessions")


def set_sessions_dir(path: Path) -> None:
    global _SESSIONS_DIR
    _SESSIONS_DIR = path


async def get_agent_connections(
    session_id: str,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """Query agent connections for a session from agents.conf."""
    session_dir = _SESSIONS_DIR / session_id
    agents = read_agents_conf(session_dir)

    results: list[dict[str, Any]] = []
    for aid, data in agents.items():
        if agent_id is not None and aid != agent_id:
            continue
        results.append({"agent_id": aid, "session_id": session_id, **data})
    return results


async def get_agent_cycles(
    session_id: str,
    connection_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query cycle records from agent_cycles.parquet."""
    parquet_path = _SESSIONS_DIR / session_id / "agent_cycles.parquet"
    if not parquet_path.exists():
        return []

    table = pq.read_table(parquet_path)
    rows = table.to_pylist()

    if connection_id is not None:
        rows = [r for r in rows if r.get("connection_id") == connection_id]

    # Most recent first
    rows.reverse()
    return rows[offset:offset + limit]


async def get_agent_summary(session_id: str) -> list[dict[str, Any]]:
    """Return per-agent aggregate stats from agents.conf."""
    session_dir = _SESSIONS_DIR / session_id
    agents = read_agents_conf(session_dir)

    results: list[dict[str, Any]] = []
    for aid, data in agents.items():
        total = data.get("total_actions", 0)
        success = data.get("successful_actions", 0)
        results.append({
            "agent_id": aid,
            "company_id": data.get("company_id"),
            "nttd_framework": data.get("nttd_framework"),
            "model": data.get("model"),
            "total_cycles": data.get("total_cycles", 0),
            "total_actions": total,
            "successful_actions": success,
            "failed_actions": data.get("failed_actions", 0),
            "avg_cycle_ms": data.get("avg_cycle_ms", 0.0),
            "avg_decide_ms": data.get("avg_decide_ms", 0.0),
            "started_at": data.get("started_at"),
            "stopped_at": data.get("stopped_at"),
            "success_rate": success / total if total > 0 else 0.0,
        })
    return results
