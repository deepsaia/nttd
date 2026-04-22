"""Async lock utility for thread-safe sly_data caching.

Follows the same pattern as neuro-san-studio's SlyDataLock. Stores an
asyncio.Lock in sly_data itself so all coded tools within a streaming_chat
invocation share the same lock instance.
"""

from asyncio import Lock
from typing import Any


class SlyDataLock:
    """Gets or creates an asyncio.Lock stored in sly_data for atomic access."""

    @staticmethod
    async def get_lock(sly_data: dict[str, Any], lock_name: str = "lock") -> Lock:
        lock: Lock = sly_data.get(lock_name)
        if lock is None:
            lock = sly_data[lock_name] = Lock()
        return lock
