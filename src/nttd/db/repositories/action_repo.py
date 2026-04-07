"""Repository for action history queries -- reads from Parquet."""

import json
import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path("logs/sessions")


def set_sessions_dir(path: Path) -> None:
    global _SESSIONS_DIR
    _SESSIONS_DIR = path


async def get_actions(
    session_id: str,
    company_id: int | None = None,
    participant_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query action history with optional filters."""
    parquet_path = _SESSIONS_DIR / session_id / "actions.parquet"
    if not parquet_path.exists():
        return []

    table = pq.read_table(parquet_path)
    rows = table.to_pylist()

    # Apply filters
    if company_id is not None:
        rows = [r for r in rows if r.get("company_id") == company_id]
    if participant_id is not None:
        rows = [r for r in rows if r.get("agent_id") == participant_id]
    if action_type is not None:
        rows = [r for r in rows if r.get("action_type") == action_type]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]

    # Reverse (most recent first) and paginate
    rows.reverse()
    return rows[offset:offset + limit]


async def get_action_params(action_id: str) -> dict[str, str]:
    """Return parameters for a specific action by parsing parameters_json."""
    # Search across all sessions (action_id includes session info)
    if not _SESSIONS_DIR.exists():
        return {}
    for session_dir in _SESSIONS_DIR.iterdir():
        parquet_path = session_dir / "actions.parquet"
        if not parquet_path.exists():
            continue
        table = pq.read_table(parquet_path, columns=["action_id", "parameters_json"])
        for i in range(table.num_rows):
            if table.column("action_id")[i].as_py() == action_id:
                params_json = table.column("parameters_json")[i].as_py()
                if params_json:
                    return json.loads(params_json)
                return {}
    return {}


async def get_action_stats(session_id: str, company_id: int | None = None) -> dict[str, Any]:
    """Return aggregate action statistics for a session."""
    parquet_path = _SESSIONS_DIR / session_id / "actions.parquet"
    if not parquet_path.exists():
        return {"total": 0, "success": 0, "failed": 0, "success_rate": 0.0}

    table = pq.read_table(parquet_path, columns=["company_id", "status"])
    rows = table.to_pylist()

    if company_id is not None:
        rows = [r for r in rows if r.get("company_id") == company_id]

    total = len(rows)
    success = sum(1 for r in rows if r.get("status") == "success")
    failed = sum(1 for r in rows if r.get("status") == "failed")

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": success / total if total > 0 else 0.0,
    }
