import asyncio
import logging
from typing import Any

from nttd.bridge.admin_client import AdminClient
from nttd.schemas.game import RuntimeMode
from nttd.schemas.snapshot import StateSnapshot
from nttd.state.world import WorldState

logger = logging.getLogger(__name__)

# How often to refresh world state via GS in async_realtime mode (seconds)
_GS_REFRESH_INTERVAL = 10.0


class Orchestrator:
    """Controls the runtime loop: heartbeat, async real-time, or assisted mode."""

    def __init__(self, world: WorldState, client: AdminClient) -> None:
        self.world = world
        self.client = client
        self._running = False
        self._heartbeat_interval_days: int = 30
        self._observers: list[Any] = []
        # Heartbeat action collection: agents push actions here before unpause
        self._pending_actions: list[dict[str, Any]] = []
        self._action_deadline: asyncio.Event = asyncio.Event()
        self._action_window_seconds: float = 5.0

    @property
    def mode(self) -> RuntimeMode:
        return self.world.game.mode

    def add_observer(self, callback: Any) -> None:
        self._observers.append(callback)

    def submit_heartbeat_action(self, action: dict[str, Any]) -> None:
        """Called by agents to submit an action during the heartbeat window."""
        self._pending_actions.append(action)

    def set_action_window(self, seconds: float) -> None:
        self._action_window_seconds = seconds

    async def _notify_observers(self, snapshot: StateSnapshot) -> None:
        for observer in self._observers:
            try:
                result = observer(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Observer error")

    async def _refresh_world_from_gs(self) -> None:
        """Query GS for all world entities and update WorldState."""
        if not self.client.connected:
            return
        try:
            # Refresh towns
            r = await self.client.send_gamescript("get_towns", timeout=15.0)
            if r.get("success") and isinstance(r.get("result"), list):
                self.world.apply_gs_towns(r["result"])

            # Refresh industries
            r = await self.client.send_gamescript("get_industries", timeout=15.0)
            if r.get("success") and isinstance(r.get("result"), list):
                self.world.apply_gs_industries(r["result"])

            # Refresh per-company stations and vehicles
            for company in list(self.world.companies.values()):
                if not company.is_active:
                    continue
                r = await self.client.send_gamescript(
                    "get_stations", {"company_id": company.id}, timeout=15.0
                )
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_stations(company.id, r["result"])

                r = await self.client.send_gamescript(
                    "get_vehicles", {"company_id": company.id}, timeout=15.0
                )
                if r.get("success") and isinstance(r.get("result"), list):
                    self.world.apply_gs_vehicles(company.id, r["result"])

        except Exception:
            logger.exception("GS world refresh failed")

    async def run_heartbeat(self, steps: int = 0) -> None:
        """Heartbeat mode: pause → refresh → snapshot → wait for actions → unpause → wait."""
        self._running = True
        step_count = 0
        logger.info("Heartbeat mode started (interval=%d days, action_window=%.1fs)",
                    self._heartbeat_interval_days, self._action_window_seconds)

        while self._running:
            # 1. Pause
            if self.client.connected:
                await self.client.send_rcon("pause")
            self.world.set_paused(True)
            await asyncio.sleep(0.2)

            # 2. Refresh world state from GS
            await self._refresh_world_from_gs()

            # 3. Snapshot
            snapshot = self.world.snapshot()
            logger.info("Heartbeat step %d: date=%d, companies=%d, towns=%d, vehicles=%d",
                        step_count, snapshot.game.game_date, len(snapshot.companies),
                        len(snapshot.towns), len(snapshot.vehicles))

            # 4. Notify observers (agents receive snapshot and can submit actions)
            self._pending_actions.clear()
            self._action_deadline.clear()
            await self._notify_observers(snapshot)

            # 5. Wait for action window
            try:
                await asyncio.wait_for(self._action_deadline.wait(), timeout=self._action_window_seconds)
            except asyncio.TimeoutError:
                pass

            # 6. Execute collected actions via GS
            if self._pending_actions:
                logger.info("Executing %d queued actions", len(self._pending_actions))
                for action in self._pending_actions:
                    try:
                        gs_action = action.get("action")
                        gs_params = action.get("params", {})
                        if gs_action and self.client.connected:
                            result = await self.client.send_gamescript(gs_action, gs_params)
                            if not result.get("success"):
                                logger.warning("Action %s failed: %s", gs_action, result.get("error"))
                    except Exception:
                        logger.exception("Failed to execute heartbeat action")
                self._pending_actions.clear()

            # 7. Unpause and let game advance
            if self.client.connected:
                await self.client.send_rcon("unpause")
            self.world.set_paused(False)

            await self._wait_game_days(self._heartbeat_interval_days)

            step_count += 1
            if steps > 0 and step_count >= steps:
                break

        if self.client.connected:
            await self.client.send_rcon("pause")
        self.world.set_paused(True)
        self._running = False
        logger.info("Heartbeat mode stopped after %d steps", step_count)

    async def run_async_realtime(self) -> None:
        """Async real-time: game runs, GS refresh + snapshot pushed periodically."""
        self._running = True
        logger.info("Async real-time mode started")
        last_gs_refresh = 0.0

        while self._running:
            await asyncio.sleep(2.0)
            now = asyncio.get_event_loop().time()

            # Periodic GS refresh
            if now - last_gs_refresh >= _GS_REFRESH_INTERVAL:
                await self._refresh_world_from_gs()
                last_gs_refresh = now

            snapshot = self.world.snapshot()
            await self._notify_observers(snapshot)

        logger.info("Async real-time mode stopped")

    def stop(self) -> None:
        self._running = False
        self._action_deadline.set()

    def set_heartbeat_interval(self, days: int) -> None:
        self._heartbeat_interval_days = days

    async def _wait_game_days(self, days: int) -> None:
        start_date = self.world.game.game_date
        target_date = start_date + days
        for _ in range(100):
            await asyncio.sleep(0.1)
            if self.world.game.game_date >= target_date or not self._running:
                return
        logger.warning("Timed out waiting for %d game-days (start=%d, current=%d)",
                       days, start_date, self.world.game.game_date)
