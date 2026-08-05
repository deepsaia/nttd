"""Per-company asyncio.Lock for action serialization.

Cross-company actions run in parallel. Same-company actions are serialized
to prevent stale-state conflicts.

Derived from the OpenTTD multiplayer/agent study, §15.2 (local research notes, not in the repo).
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CompanyLockManager:
    """Manages per-company locks for action serialization."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    def get_lock(self, company_id: int) -> asyncio.Lock:
        if company_id not in self._locks:
            self._locks[company_id] = asyncio.Lock()
        return self._locks[company_id]

    async def acquire(self, company_id: int) -> None:
        lock = self.get_lock(company_id)
        await lock.acquire()

    def release(self, company_id: int) -> None:
        lock = self._locks.get(company_id)
        if lock and lock.locked():
            lock.release()

    def is_locked(self, company_id: int) -> bool:
        lock = self._locks.get(company_id)
        return lock is not None and lock.locked()

    def status(self) -> dict[str, Any]:
        return {
            "companies": len(self._locks),
            "locked": [cid for cid, lock in self._locks.items() if lock.locked()],
        }

    def clear(self) -> None:
        self._locks.clear()
