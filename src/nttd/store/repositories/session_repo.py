"""Session CRUD, over one session.parquet per session directory.

The agents.conf functions that used to sit here are gone, along with the
server-driven gameloop that wrote that file: participant identity now comes from the
live token registry, and spend from POST /report.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from nttd.store import session_paths
from nttd.store.conf_writer import read_session_conf, update_session_conf, write_session_conf

logger = logging.getLogger(__name__)


async def create_session(
    session_id: str,
    name: str = "",
    status: str = "pending",
    game_start_date: int | None = None,
    game_port: int | None = None,
    admin_port: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    session_dir = session_paths.session_dir(session_id)
    write_session_conf(
        session_dir=session_dir,
        session_id=session_id,
        name=name,
        status=status,
        created_at=datetime.now(timezone.utc).isoformat(),
        game_port=game_port,
        admin_port=admin_port,
        meta=meta,
    )


async def update_session_name(session_id: str, name: str) -> None:
    session_dir = session_paths.session_dir(session_id)
    update_session_conf(session_dir, {"session.name": name})


async def update_session_ports(
    session_id: str,
    game_port: int,
    admin_port: int,
) -> None:
    session_dir = session_paths.session_dir(session_id)
    update_session_conf(session_dir, {
        "session.game_port": game_port,
        "session.admin_port": admin_port,
    })


async def update_session_pid(session_id: str, pid: int | None) -> None:
    session_dir = session_paths.session_dir(session_id)
    update_session_conf(session_dir, {"session.pid": pid or 0})


async def mark_session_active(session_id: str, pid: int) -> None:
    session_dir = session_paths.session_dir(session_id)
    update_session_conf(session_dir, {
        "session.status": "active",
        "session.pid": pid,
        "session.started_at": datetime.now(timezone.utc).isoformat(),
    })


async def get_active_sessions_with_ports() -> list[dict[str, Any]]:
    """Return all sessions with status 'active' that have ports and pid set."""
    results: list[dict[str, Any]] = []
    for session_dir in session_paths.iter_session_dirs():
        data = read_session_conf(session_dir)
        if data and data.get("status") == "active" and data.get("pid"):
            results.append(data)
    return results


async def end_session(
    session_id: str,
    end_reason: str = "completed",
    game_end_date: int | None = None,
) -> None:
    session_dir = session_paths.session_dir(session_id)
    updates: dict[str, Any] = {
        "session.status": "ended",
        "session.ended_at": datetime.now(timezone.utc).isoformat(),
        "session.end_reason": end_reason,
    }
    if game_end_date is not None:
        updates["session.game_end_date"] = game_end_date
    update_session_conf(session_dir, updates)


async def get_session_by_id(session_id: str) -> dict[str, Any] | None:
    session_dir = session_paths.session_dir(session_id)
    return read_session_conf(session_dir)


async def archive_session(session_id: str) -> None:
    session_dir = session_paths.session_dir(session_id)
    update_session_conf(session_dir, {
        "session.status": "archived",
        "session.ended_at": datetime.now(timezone.utc).isoformat(),
    })


async def delete_session(session_id: str) -> None:
    """Delete session directory entirely."""
    import shutil
    session_dir = session_paths.session_dir(session_id)
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)


async def list_sessions(
    status: str | None = None, include_archived: bool = False, limit: int = 50,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for session_dir in session_paths.iter_session_dirs():
        data = read_session_conf(session_dir)
        if data is None:
            continue
        s = data.get("status", "")
        if status and s != status:
            continue
        if not include_archived and s == "archived":
            continue
        results.append(data)
        if len(results) >= limit:
            break
    return results


async def upsert_settings(session_id: str, settings: dict[str, str]) -> None:
    """Store effective settings in session.parquet.

    Reads the existing data, merges settings, and rewrites the file.
    """
    session_dir = session_paths.session_dir(session_id)
    parquet_path = session_dir / "session.parquet"
    if not parquet_path.exists():
        write_session_conf(
            session_dir=session_dir,
            session_id=session_id,
            settings=settings,
        )
        return

    try:
        data = read_session_conf(session_dir)
        if data is None:
            return

        # Merge new settings into existing
        existing_settings = data.get("settings", {})
        existing_settings.update(settings)

        # Rewrite session.conf with merged settings
        write_session_conf(
            session_dir=session_dir,
            session_id=data.get("session_id", session_id),
            name=data.get("name", ""),
            status=data.get("status", "active"),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            end_reason=data.get("end_reason"),
            game_port=data.get("game_port"),
            admin_port=data.get("admin_port"),
            pid=data.get("pid"),
            settings=existing_settings,
            meta=data.get("meta"),
        )
    except Exception:
        logger.exception("Failed to upsert settings for session %s", session_id)


async def get_settings(session_id: str) -> dict[str, str]:
    session_dir = session_paths.session_dir(session_id)
    data = read_session_conf(session_dir)
    if data is None:
        return {}
    return data.get("settings", {})


