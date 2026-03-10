import asyncio
import logging
from typing import Any

from nttd.bridge.admin_client import AdminClient
from nttd.schemas.game import RuntimeMode
from nttd.schemas.snapshot import StateSnapshot
from nttd.state.world import WorldState

logger = logging.getLogger(__name__)


class Orchestrator:
    """Controls the runtime loop: heartbeat, async real-time, or assisted mode."""

    def __init__(self, world: WorldState, client: AdminClient) -> None:
        self.world = world
        self.client = client
        self._running = False
        self._heartbeat_interval_days: int = 30
        self._observers: list[Any] = []

    @property
    def mode(self) -> RuntimeMode:
        return self.world.game.mode

    def add_observer(self, callback: Any) -> None:
        self._observers.append(callback)

    async def _notify_observers(self, snapshot: StateSnapshot) -> None:
        for observer in self._observers:
            try:
                result = observer(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Observer error")

    async def run_heartbeat(self, steps: int = 0) -> None:
        """Run heartbeat mode: pause → snapshot → notify → unpause → wait → repeat.

        Args:
            steps: Number of heartbeat cycles. 0 means run indefinitely.
        """
        self._running = True
        step_count = 0
        logger.info("Heartbeat mode started (interval=%d game-days)", self._heartbeat_interval_days)

        while self._running:
            # 1. Pause
            if self.client.connected:
                await self.client.send_rcon("pause")
            self.world.set_paused(True)

            # 2. Wait briefly for state to settle
            await asyncio.sleep(0.2)

            # 3. Snapshot
            snapshot = self.world.snapshot()
            logger.info(
                "Heartbeat step %d: date=%d, companies=%d",
                step_count, snapshot.game.game_date, len(snapshot.companies),
            )

            # 4. Notify observers (agents collect this snapshot)
            await self._notify_observers(snapshot)

            # 5. Unpause and let game advance
            if self.client.connected:
                await self.client.send_rcon("unpause")
            self.world.set_paused(False)

            # 6. Wait for game to advance
            await self._wait_game_days(self._heartbeat_interval_days)

            step_count += 1
            if steps > 0 and step_count >= steps:
                break

        # Final pause
        if self.client.connected:
            await self.client.send_rcon("pause")
        self.world.set_paused(True)
        self._running = False
        logger.info("Heartbeat mode stopped after %d steps", step_count)

    async def run_async_realtime(self) -> None:
        """Run async real-time mode: game runs continuously, periodic snapshots pushed."""
        self._running = True
        logger.info("Async real-time mode started")

        while self._running:
            await asyncio.sleep(2.0)
            snapshot = self.world.snapshot()
            await self._notify_observers(snapshot)

        logger.info("Async real-time mode stopped")

    def stop(self) -> None:
        self._running = False

    def set_heartbeat_interval(self, days: int) -> None:
        self._heartbeat_interval_days = days

    async def _wait_game_days(self, days: int) -> None:
        """Wait until the game has advanced by approximately `days` game-days."""
        start_date = self.world.game.game_date
        target_date = start_date + days

        for _ in range(100):
            await asyncio.sleep(0.1)
            if self.world.game.game_date >= target_date:
                return
            if not self._running:
                return

        logger.warning(
            "Timed out waiting for %d game-days (start=%d, current=%d)",
            days, start_date, self.world.game.game_date,
        )
