"""Auto-apply database schema on startup.

Creates all tables defined in tables.py if they don't exist.
Future numbered migrations can be added for schema evolution.
"""

import logging

from nttd.db.engine import get_engine
from nttd.db.tables import metadata

logger = logging.getLogger(__name__)


async def apply_migrations() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    logger.info("Database schema applied (%d tables).", len(metadata.tables))
