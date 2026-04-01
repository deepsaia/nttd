"""Repository for session CRUD and queries."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select, update

from nttd.db.engine import get_session
from nttd.db.tables import participants, session_settings, sessions


async def create_session(
    session_id: str,
    name: str = "",
    status: str = "active",
    game_start_date: int | None = None,
) -> None:
    async with get_session() as db:
        await db.execute(
            insert(sessions).values(
                id=session_id,
                name=name,
                status=status,
                started_at=datetime.now(timezone.utc),
                game_start_date=game_start_date,
            )
        )
        await db.commit()


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


async def get_session_by_id(session_id: str) -> dict[str, Any] | None:
    async with get_session() as db:
        row = (await db.execute(select(sessions).where(sessions.c.id == session_id))).first()
        if row is None:
            return None
        return dict(row._mapping)


async def list_sessions(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    async with get_session() as db:
        q = select(sessions).order_by(sessions.c.created_at.desc()).limit(limit)
        if status:
            q = q.where(sessions.c.status == status)
        rows = (await db.execute(q)).fetchall()
        return [dict(r._mapping) for r in rows]


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
