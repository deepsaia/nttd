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
from nttd.logging.event_logger import EventLogger
from nttd.runtime.orchestrator import Orchestrator
from nttd.state.agent_registry import AgentRegistry
from nttd.state.snapshot_broker import AgentSnapshotBroker
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
        self.orchestrator = Orchestrator(self.world, self.admin_client)
        self.action_tracker = ActionTracker()
        self.agent_registry = AgentRegistry()
        self.event_logger = EventLogger()
        self.snapshot_broker_registry: dict[str, AgentSnapshotBroker] = {}

        self.process: asyncio.subprocess.Process | None = None
        self.poll_task: asyncio.Task[None] | None = None

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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Poll until admin port is connectable
        connected = await self._wait_for_admin_port(admin_password)
        if not connected:
            logger.error("Failed to connect to session %s after %.0fs", self.session_id, _CONNECT_MAX_WAIT)
            await self.shutdown()
            return False

        # Start the receive loop
        self.poll_task = asyncio.create_task(
            self.admin_client.poll_loop(),
            name=f"poll_{self.session_id}",
        )

        logger.info("Session %s server started (PID %s)", self.session_id, self.process.pid)
        return True

    async def connect_to_existing(self, admin_password: str) -> bool:
        """Connect to an already-running OpenTTD server (orphan recovery)."""
        ok = await self.admin_client.connect(password=admin_password, name=f"nttd_{self.session_id}")
        if ok:
            self.poll_task = asyncio.create_task(
                self.admin_client.poll_loop(),
                name=f"poll_{self.session_id}",
            )
        return ok

    async def apply_settings_and_start(self, settings: dict[str, str], ai_count: int = 0) -> list[str]:
        """Apply game settings via rcon and start a new game."""
        for key, value in settings.items():
            await self.admin_client.send_rcon(f"setting {key} {value}")

        if ai_count > 0:
            await self.admin_client.send_rcon("setting ai_in_multiplayer true")
            await self.admin_client.send_rcon(f"setting difficulty.max_no_competitors {ai_count}")

        response = await self.admin_client.send_rcon("newgame")
        return response

    async def shutdown(self) -> None:
        """Stop the server process and clean up."""
        logger.info("Shutting down session %s", self.session_id)

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
                stderr = await self.process.stderr.read() if self.process.stderr else b""
                logger.error(
                    "OpenTTD process exited with code %d: %s",
                    self.process.returncode, stderr.decode(errors="replace")[:500],
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
