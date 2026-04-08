"""Per-session runtime bundle.

Each SessionRuntime owns an OpenTTD server process and the full stack
needed to interact with it: AdminClient, WorldState, Bridge, Orchestrator.
"""

import asyncio
import logging
from pathlib import Path

from nttd.actions.tracker import ActionTracker
from nttd.bridge.admin_client import AdminClient
from nttd.bridge.bridge import Bridge
from nttd.db.recorder import SessionRecorder
from nttd.db.tile_writer import TileWriter
from nttd.gameloop.manager import GameloopManager
from nttd.runtime.orchestrator import Orchestrator
from nttd.state.agent_registry import AgentRegistry
from nttd.state.snapshot_broker import AgentSnapshotBroker
from nttd.state.snapshot_class import SnapshotClassRegistry
from nttd.state.world import WorldState

logger = logging.getLogger(__name__)

_CONNECT_POLL_INTERVAL = 0.5  # seconds between connection attempts
_CONNECT_MAX_WAIT = 15.0  # max seconds to wait for server to start
_SHUTDOWN_TIMEOUT = 5.0  # seconds to wait for graceful shutdown


class SessionRuntime:
    """Bundles all per-session objects and the OpenTTD server process."""

    def __init__(
        self,
        session_id: str,
        game_port: int,
        admin_port: int,
        config_dir: Path,
    ) -> None:
        self.session_id = session_id
        self.game_port = game_port
        self.admin_port = admin_port
        self.config_dir = config_dir

        self.world = WorldState()
        self.admin_client = AdminClient(host="127.0.0.1", port=admin_port)
        self.bridge = Bridge(self.world, self.admin_client)
        self.recorder = SessionRecorder(session_id, data_dir="logs/sessions")
        self.orchestrator = Orchestrator(self.world, self.admin_client, recorder=self.recorder)
        self.action_tracker = ActionTracker()
        self.agent_registry = AgentRegistry()
        self.snapshot_broker_registry: dict[str, AgentSnapshotBroker] = {}
        self.snapshot_class_registry = SnapshotClassRegistry()
        self.tile_writer = TileWriter(session_id, data_dir="logs/sessions")
        self.gameloop_manager = GameloopManager(self)

        # Stop all gameloop agents when the session ends
        self.orchestrator.on_end.append(lambda _reason: self.gameloop_manager.stop_all())

        self.process: asyncio.subprocess.Process | None = None
        self.poll_task: asyncio.Task[None] | None = None
        self.orchestrator_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self.admin_client.connected

    async def start_server(
        self,
        openttd_binary: str,
        admin_password: str,
    ) -> bool:
        """Spawn the OpenTTD dedicated server and connect the admin client.

        Returns True if server started and admin client connected successfully.
        """
        cfg_path = str(self.config_dir / "openttd.cfg")
        logger.info(
            "Starting OpenTTD for session %s (game=%d, admin=%d): %s -D -c %s",
            self.session_id, self.game_port, self.admin_port,
            openttd_binary, cfg_path,
        )

        self.process = await asyncio.create_subprocess_exec(
            openttd_binary, "-D", "-c", cfg_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Poll until admin port is connectable
        connected = await self._wait_for_admin_port(admin_password)
        if not connected:
            logger.error("Failed to connect to session %s after %.0fs", self.session_id, _CONNECT_MAX_WAIT)
            await self.shutdown()
            return False

        # Apply welcome data (map size, landscape) to world state
        if self.admin_client.welcome:
            self.bridge.apply_welcome(self.admin_client.welcome)

        # Start the receive loop
        self.poll_task = asyncio.create_task(
            self.admin_client.poll_loop(),
            name=f"poll_{self.session_id}",
        )

        # Start the DB recorder
        await self.recorder.start()

        logger.info("Session %s server started (PID %s)", self.session_id, self.process.pid)
        return True

    async def connect_to_existing(self, admin_password: str) -> bool:
        """Connect to an already-running OpenTTD server (orphan recovery)."""
        ok = await self.admin_client.connect(password=admin_password, name=f"nttd_{self.session_id}")
        if ok:
            if self.admin_client.welcome:
                self.bridge.apply_welcome(self.admin_client.welcome)
            self.poll_task = asyncio.create_task(
                self.admin_client.poll_loop(),
                name=f"poll_{self.session_id}",
            )
            await self.recorder.start()
        return ok

    async def start_companies(
        self,
        ai_count: int = 0,
        agent_companies: int = 0,
    ) -> None:
        """Verify AI companies and GS after initial game starts.

        AI companies are configured in openttd.cfg (max_no_competitors,
        competitors_interval=0) so they auto-start during map generation.
        This method verifies the GS is responding and logs company status.
        """
        total = ai_count + agent_companies

        # Verify GS is responding
        ping_result = await self.admin_client.send_gamescript("ping")
        if ping_result.get("success"):
            logger.info("GameScript responding for session %s", self.session_id)
        else:
            logger.warning("GameScript not responding for session %s: %s", self.session_id, ping_result)

        # Initial world state refresh — populate towns, industries, companies
        # so gameloop agents and state endpoints have data immediately.
        await self.orchestrator._refresh_world_from_gs()
        logger.info(
            "Initial world refresh for session %s: %d towns, %d companies",
            self.session_id, len(self.world.towns), len(self.world.companies),
        )

        # Capture tile terrain in the background (non-blocking)
        asyncio.create_task(self._capture_tiles(), name=f"tiles_{self.session_id}")

        # Verify companies were auto-created
        if total > 0:
            rcon = await self.admin_client.send_rcon("companies")
            company_count = len([line for line in rcon if line.strip()])
            if company_count >= total:
                logger.info(
                    "Verified %d company(ies) for session %s (%d agent slots, %d AI)",
                    company_count, self.session_id, agent_companies, ai_count,
                )
            else:
                logger.warning(
                    "Expected %d companies but found %d for session %s",
                    total, company_count, self.session_id,
                )

    async def _capture_tiles(self) -> None:
        """Capture full tile terrain data in the background."""
        try:
            result = await self.admin_client.send_gamescript(
                "get_map_terrain", {}, timeout=60.0,
            )
            if result.get("success") and isinstance(result.get("result"), list):
                count = self.tile_writer.write_full_scan(result["result"])
                logger.info("Tile capture complete for session %s: %d tiles", self.session_id, count)
            else:
                logger.warning(
                    "Tile capture failed for session %s: %s",
                    self.session_id, result.get("error", "unknown"),
                )
        except Exception:
            logger.exception("Tile capture error for session %s", self.session_id)

    def start_orchestrator(self, mode: str = "async_realtime") -> None:
        """Start the orchestrator loop for snapshot capture and end-condition checks."""
        if self.orchestrator_task and not self.orchestrator_task.done():
            logger.warning("Orchestrator already running for session %s", self.session_id)
            return

        self.orchestrator.stop()  # reset running flag

        if mode == "heartbeat":
            self.orchestrator_task = asyncio.create_task(
                self.orchestrator.run_heartbeat(),
                name=f"orchestrator-{self.session_id}",
            )
        elif mode == "async_realtime":
            self.orchestrator_task = asyncio.create_task(
                self.orchestrator.run_async_realtime(),
                name=f"orchestrator-{self.session_id}",
            )
        else:
            logger.warning("Unknown orchestrator mode %r, not starting", mode)
            return

        logger.info("Orchestrator started for session %s in %s mode", self.session_id, mode)

    async def shutdown(self) -> None:
        """Stop the server process and clean up."""
        logger.info("Shutting down session %s", self.session_id)

        # Stop orchestrator loop
        self.orchestrator.stop()
        if self.orchestrator_task and not self.orchestrator_task.done():
            self.orchestrator_task.cancel()
            try:
                await self.orchestrator_task
            except asyncio.CancelledError:
                pass
            self.orchestrator_task = None

        # Stop all gameloop agents first
        await self.gameloop_manager.stop_all()

        # Stop the DB recorder (flushes remaining buffers)
        await self.recorder.stop()

        # Cancel poll loop
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
            self.poll_task = None

        # Graceful quit via rcon (best effort)
        if self.admin_client.connected:
            try:
                await self.admin_client.send_rcon("quit")
            except Exception:
                pass
            await self.admin_client.disconnect()

        # Terminate process
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=_SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Session %s did not exit gracefully, killing", self.session_id)
                self.process.kill()
                await self.process.wait()
            self.process = None

        logger.info("Session %s shut down", self.session_id)

    async def _wait_for_admin_port(self, password: str) -> bool:
        """Poll until the admin port is connectable or timeout."""
        elapsed = 0.0
        while elapsed < _CONNECT_MAX_WAIT:
            # Check if process died
            if self.process and self.process.returncode is not None:
                logger.error(
                    "OpenTTD process exited with code %d",
                    self.process.returncode,
                )
                return False

            ok = await self.admin_client.connect(
                password=password,
                name=f"nttd_{self.session_id}",
            )
            if ok:
                return True

            await asyncio.sleep(_CONNECT_POLL_INTERVAL)
            elapsed += _CONNECT_POLL_INTERVAL

        return False
