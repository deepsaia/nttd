import logging
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: sessionmaker | None = None


def _set_wal_mode(dbapi_conn: object, _connection_record: object) -> None:
    cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def init_engine(db_path: str = "nttd.db") -> AsyncEngine:
    global _engine, _session_factory

    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{path}"

    _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    event.listen(_engine.sync_engine, "connect", _set_wal_mode)

    _session_factory = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    logger.info("Database engine initialized: %s", path)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _engine


def get_session() -> AsyncSession:
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _session_factory()


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine closed.")


async def execute_sql(sql_text: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        for statement in sql_text.split(";"):
            stripped = statement.strip()
            if stripped:
                await conn.execute(text(stripped))
