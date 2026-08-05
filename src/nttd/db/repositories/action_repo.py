"""Action history queries, over the shared Parquet read path."""

from __future__ import annotations

import json
import logging
from typing import Any

from nttd.db import parquet_reader, session_paths

logger = logging.getLogger(__name__)

_ACTIONS = "actions"


async def get_actions(
    session_id: str,
    company_id: int | None = None,
    participant_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query action history with optional filters, most recent first."""
    rows = parquet_reader.read_rows(session_id, _ACTIONS)

    if company_id is not None:
        rows = [r for r in rows if r.get("company_id") == company_id]
    if participant_id is not None:
        rows = [r for r in rows if r.get("agent_id") == participant_id]
    if action_type is not None:
        rows = [r for r in rows if r.get("action_type") == action_type]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]

    rows.reverse()
    return rows[offset:offset + limit]


async def get_action_params(action_id: str) -> dict[str, str]:
    """Return the parameters of one action, searching every session for its id."""
    for session_dir in session_paths.iter_session_dirs():
        rows = parquet_reader.read_rows(
            session_dir.name, _ACTIONS, ["action_id", "parameters_json"],
        )
        for row in rows:
            if row.get("action_id") != action_id:
                continue
            params_json = row.get("parameters_json")
            return json.loads(params_json) if params_json else {}
    return {}


async def get_action_stats(session_id: str, company_id: int | None = None) -> dict[str, Any]:
    """Return aggregate action statistics for a session."""
    rows = parquet_reader.read_rows(session_id, _ACTIONS, ["company_id", "status"])

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
