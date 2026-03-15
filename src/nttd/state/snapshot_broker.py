import asyncio
from collections import deque

from nttd.schemas.snapshot import StateSnapshot


class AgentSnapshotBroker:
    """Per-agent delivery buffer synchronized with the heartbeat beat.

    maxsize=1 ensures agents always see the latest snapshot, never queue lag.
    History deque provides trend data without unbounded heap growth.
    """

    def __init__(self, history_len: int = 5) -> None:
        self._queue: asyncio.Queue[StateSnapshot] = asyncio.Queue(maxsize=1)
        self._history: deque[StateSnapshot] = deque(maxlen=history_len)

    async def push_snapshot(self, snapshot: StateSnapshot) -> None:
        """Drop stale unread snapshot and insert newest (non-blocking)."""
        try:
            self._queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(snapshot)
        self._history.append(snapshot)

    async def wait_for_snapshot(self) -> StateSnapshot:
        return await self._queue.get()

    def get_history(self, n: int = 5) -> list[StateSnapshot]:
        snaps = list(self._history)
        return list(reversed(snaps[-n:]))
