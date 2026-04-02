"""Repository for session CRUD and queries."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, insert, select, update

from nttd.db.engine import get_session
from nttd.db.tables import participants, session_settings, sessions


async def create_session(
    session_id: str,
    name: str = "",
    status: str = "pending",
    game_start_date: int | None = None,
    game_port: int | None = None,
    admin_port: int | None = None,
) -> None:
    async with get_session() as db:
        await db.execute(
            insert(sessions).values(
                id=session_id,
                name=name,
                status=status,
                game_start_date=game_start_date,
                game_port=game_port,
                admin_port=admin_port,
            )
        )
        await db.commit()


async def update_session_name(session_id: str, name: str) -> None:
    async with get_session() as db:
        await db.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(name=name)
        )
        await db.commit()


async def update_session_ports(
    session_id: str,
    game_port: int,
    admin_port: int,
) -> None:
    async with get_session() as db:
        await db.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(game_port=game_port, admin_port=admin_port)
        )
        await db.commit()


async def update_session_pid(session_id: str, pid: int | None) -> None:
    async with get_session() as db:
        await db.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(pid=pid)
        )
        await db.commit()


async def mark_session_active(session_id: str, pid: int) -> None:
    async with get_session() as db:
        await db.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(
                status="active",
                pid=pid,
                started_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def get_active_sessions_with_ports() -> list[dict[str, Any]]:
    """Return all sessions with status 'active' that have ports and pid set."""
    async with get_session() as db:
        rows = (
            await db.execute(
                select(sessions).where(
                    sessions.c.status == "active",
                    sessions.c.pid.is_not(None),
                )
            )
        ).fetchall()
        return [_normalize_session(r._mapping) for r in rows]


async def end_session(
    session_id: str,
    end_reason: str = "completed",
    game_end_date: int | None = None,
) -> None:
    async with get_session() as db:
        await db.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(
                status="ended",
                ended_at=datetime.now(timezone.utc),
                end_reason=end_reason,
                game_end_date=game_end_date,
            )
        )
        await db.commit()


def _normalize_session(row_mapping: Any) -> dict[str, Any]:
    """Rename DB 'id' to 'session_id' for API consistency."""
    d = dict(row_mapping)
    if "id" in d and "session_id" not in d:
        d["session_id"] = d.pop("id")
    return d


async def get_session_by_id(session_id: str) -> dict[str, Any] | None:
    async with get_session() as db:
        row = (await db.execute(select(sessions).where(sessions.c.id == session_id))).first()
        if row is None:
            return None
        return _normalize_session(row._mapping)


async def archive_session(session_id: str) -> None:
    async with get_session() as db:
        await db.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(status="archived", ended_at=datetime.now(timezone.utc))
        )
        await db.commit()


async def delete_session(session_id: str) -> None:
    async with get_session() as db:
        await db.execute(delete(session_settings).where(session_settings.c.session_id == session_id))
        await db.execute(delete(participants).where(participants.c.session_id == session_id))
        await db.execute(delete(sessions).where(sessions.c.id == session_id))
        await db.commit()


async def list_sessions(
    status: str | None = None, include_archived: bool = False, limit: int = 50,
) -> list[dict[str, Any]]:
    async with get_session() as db:
        q = select(sessions).order_by(sessions.c.created_at.desc()).limit(limit)
        if status:
            q = q.where(sessions.c.status == status)
        elif not include_archived:
            q = q.where(sessions.c.status != "archived")
        rows = (await db.execute(q)).fetchall()
        return [_normalize_session(r._mapping) for r in rows]


async def upsert_settings(session_id: str, settings: dict[str, str]) -> None:
    async with get_session() as db:
        for key, value in settings.items():
            existing = (
                await db.execute(
                    select(session_settings).where(
                        session_settings.c.session_id == session_id,
                        session_settings.c.key == key,
                    )
                )
            ).first()
            if existing:
                await db.execute(
                    update(session_settings)
                    .where(session_settings.c.id == existing.id)
                    .values(value=str(value))
                )
            else:
                await db.execute(
                    insert(session_settings).values(
                        session_id=session_id, key=key, value=str(value)
                    )
                )
        await db.commit()


async def get_settings(session_id: str) -> dict[str, str]:
    async with get_session() as db:
        rows = (
            await db.execute(
                select(session_settings).where(session_settings.c.session_id == session_id)
            )
        ).fetchall()
        return {r.key: r.value for r in rows}


async def add_participant(
    session_id: str,
    participant_id: str,
    participant_type: str,
    name: str | None = None,
    company_id: int | None = None,
    config: str | None = None,
) -> None:
    async with get_session() as db:
        await db.execute(
            insert(participants).values(
                session_id=session_id,
                participant_id=participant_id,
                participant_type=participant_type,
                name=name,
                company_id=company_id,
                config=config,
            )
        )
        await db.commit()


async def list_participants(session_id: str) -> list[dict[str, Any]]:
    async with get_session() as db:
        rows = (
            await db.execute(
                select(participants).where(participants.c.session_id == session_id)
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]
