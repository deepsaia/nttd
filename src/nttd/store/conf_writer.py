"""Session metadata and agent connection writer/reader.

Writes session.parquet and agents.parquet under each session's log directory.
"""

import json
import logging
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# session.parquet -- single-row DataFrame with session metadata
# ---------------------------------------------------------------------------

_SESSION_FIELDS = [
    "session_id", "name", "status", "created_at", "started_at",
    "ended_at", "end_reason", "game_port", "admin_port", "pid",
]


def write_session_conf(
    session_dir: Path,
    session_id: str,
    name: str = "",
    status: str = "active",
    created_at: str | None = None,
    started_at: str | None = None,
    ended_at: str | None = None,
    end_reason: str | None = None,
    game_port: int | None = None,
    admin_port: int | None = None,
    pid: int | None = None,
    settings: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write or overwrite session.parquet with current session state."""
    session_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = session_dir / "session.parquet"

    row: dict[str, Any] = {
        "session_id": session_id,
        "name": name or "",
        "status": status,
        "created_at": created_at or "",
        "started_at": started_at or "",
        "ended_at": ended_at or "",
        "end_reason": end_reason or "",
        "game_port": game_port or 0,
        "admin_port": admin_port or 0,
        "pid": pid or 0,
        "settings_json": json.dumps(settings) if settings else "{}",
        "meta_json": json.dumps(meta) if meta else "{}",
    }

    df = pl.DataFrame([row])
    df.write_parquet(parquet_path)
    logger.debug("Wrote session.parquet: %s", parquet_path)
    return parquet_path


def update_session_conf(
    session_dir: Path,
    updates: dict[str, Any],
) -> None:
    """Update specific fields in session.parquet.

    Keys use dot-separated paths: 'session.status', 'session.ended_at', etc.
    The 'session.' prefix is stripped to get the column name.
    """
    data = read_session_conf(session_dir)
    if data is None:
        logger.warning("Cannot update session -- no data found: %s", session_dir)
        return

    for key, value in updates.items():
        field = key.removeprefix("session.")
        data[field] = value

    settings = data.pop("settings", None)
    meta = data.pop("meta", None)

    write_session_conf(
        session_dir=session_dir,
        session_id=data.get("session_id", ""),
        name=data.get("name", ""),
        status=data.get("status", ""),
        created_at=data.get("created_at"),
        started_at=data.get("started_at"),
        ended_at=data.get("ended_at"),
        end_reason=data.get("end_reason"),
        game_port=data.get("game_port"),
        admin_port=data.get("admin_port"),
        pid=data.get("pid"),
        settings=settings,
        meta=meta,
    )


def read_session_conf(session_dir: Path) -> dict[str, Any] | None:
    """Read session metadata from session.parquet."""
    parquet_path = session_dir / "session.parquet"
    if not parquet_path.exists():
        return None

    try:
        df = pl.read_parquet(parquet_path)
        if df.is_empty():
            return None
        row = df.row(0, named=True)
        result: dict[str, Any] = {}
        for field in _SESSION_FIELDS:
            if field in row:
                result[field] = row[field]
        settings_raw = row.get("settings_json", "{}")
        result["settings"] = json.loads(settings_raw) if settings_raw else {}
        meta_raw = row.get("meta_json", "{}")
        result["meta"] = json.loads(meta_raw) if meta_raw else {}
        return result
    except Exception:
        logger.exception("Failed to read session.parquet at %s", parquet_path)
        return None


# ---------------------------------------------------------------------------
# agents.parquet -- one row per agent
# ---------------------------------------------------------------------------

