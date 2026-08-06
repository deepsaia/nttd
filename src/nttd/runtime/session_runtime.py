"""Per-session runtime bundle.

Each SessionRuntime owns an OpenTTD server process and the full stack
needed to interact with it: AdminClient, WorldState, Bridge, Orchestrator.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from nttd.actions.tracker import ActionTracker
from nttd.bridge.admin_client import AdminClient
from nttd.bridge.bridge import Bridge
from nttd.config.task_instance import TaskInstance
from nttd.runtime.orchestrator import Orchestrator
from nttd.runtime.participant_registry import ParticipantRegistry
from nttd.runtime.participant_report import ParticipantReport
from nttd.runtime.scored_lock import ScoredLock
from nttd.runtime.step_barrier import StepBarrier
from nttd.state.agent_registry import AgentRegistry
from nttd.state.snapshot_broker import AgentSnapshotBroker
from nttd.state.snapshot_class import SnapshotClassRegistry
from nttd.state.world import WorldState
from nttd.store.recorder import SessionRecorder
from nttd.store.tile_writer import TileWriter
from nttd.utils.name_generator import generate_company_name

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
        data_dir: Path | str | None = None,
    ) -> None:
        """Bundle the per-session stack.

        Args:
            data_dir: Where recorded artifacts go. Defaults to the parent of
                config_dir, which is the session directory, so parquet output lands
                beside the config and result rather than in a hardcoded path that
                ignores NTTD_SESSIONS_DIR.
        """
        self.session_id = session_id
        self.game_port = game_port
        self.admin_port = admin_port
        self.config_dir = config_dir
        # Seed this session's map was generated from, for provenance. Set by
        # SessionManager; None means the map was generated randomly.
        self.map_seed: int | None = None
        # Identity of the problem being played, for the result record. Set by
        # SessionManager; None if the session was created without a scenario.
        self.task_instance: TaskInstance | None = None
        # Run shape, captured at start so the result record can report what was
        # actually played rather than inferring it afterwards.
        self.runtime_mode: str = ""
        self.started_at: float = 0.0
        self.start_game_date: int = 0
        # The world settings a scored scenario is allowed to vary, in readable form
        # (``{"landscape": "temperate", ...}``). Held here so the result record can
        # publish them as leaderboard columns: they may differ between scored runs
        # only on condition of being disclosed, since disclosure is what lets a
        # reader judge whether two rows are comparable.
        self.dimensions: dict[str, str] = {}

        self.world = WorldState()
        self.admin_client = AdminClient(host="127.0.0.1", port=admin_port)
        self.bridge = Bridge(self.world, self.admin_client)
        # Default to the session directory's parent so artifacts follow
        # NTTD_SESSIONS_DIR instead of a hardcoded path.
        self.data_dir = str(data_dir) if data_dir else str(Path(config_dir).parent)
        self.recorder = SessionRecorder(session_id, data_dir=self.data_dir)
        self.orchestrator = Orchestrator(self.world, self.admin_client, recorder=self.recorder)
        # Commands issued in the OpenTTD game window land in the same action log as
        # API submissions, tagged with their source. Registered here rather than at
        # connect time because the callback outlives a reconnect.
        self.admin_client.on_client_command(self._record_client_command)
        self.action_tracker = ActionTracker()
        self.agent_registry = AgentRegistry()
        self.snapshot_broker_registry: dict[str, AgentSnapshotBroker] = {}
        self.snapshot_class_registry = SnapshotClassRegistry()
        # Maps participant tokens to the company they may act as. Populated when
        # the session starts; empty means no company is claimed yet.
        self.participants = ParticipantRegistry()
        # Whether this session is scored, and what it refused. This is the real
        # protection for a benchmark run: session state rather than a credential,
        # because a self-hosting contestant holds every credential anyway.
        self.scored_lock = ScoredLock()
        self.tile_writer = TileWriter(session_id, data_dir=self.data_dir)
        # Per-company contestant detail for the result record. The contestant runs
        # its own loop, so nttd tallies action counts from its own action log and
        # records model and spend only as declared. See participant_report.
        self.participant_report = ParticipantReport()
        # Synchronises several companies stepping one shared world. With a single
        # stepper it is a pass-through: that company is the last arriver on arrival and
        # drives the advance immediately. See step_barrier for why the clock has to be
        # shared even though participation is not.
        self.step_barrier = StepBarrier()
        self.step_barrier.set_evict_callback(self._record_eviction)

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
        map_seed: int | None = None,
    ) -> bool:
        """Spawn the OpenTTD dedicated server and connect the admin client.

        Args:
            openttd_binary: Path to the OpenTTD executable.
            admin_password: Password for admin port authentication.
            map_seed: Map generation seed. Passed as ``-G`` because OpenTTD 15.3
                does not pin generation from ``game_creation.generation_seed``
                in the config alone -- only the command-line flag does. Omitting
                it yields a random map.

        Returns True if server started and admin client connected successfully.
        """
        cfg_path = str(self.config_dir / "openttd.cfg")
        argv = [openttd_binary, "-D", "-c", cfg_path]
        if map_seed is not None:
            argv += ["-G", str(map_seed)]
        logger.info(
            "Starting OpenTTD for session %s (game=%d, admin=%d): %s",
            self.session_id, self.game_port, self.admin_port,
            " ".join(argv),
        )

        self.process = await asyncio.create_subprocess_exec(
            *argv,
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
        # so a contestant's first observation has data immediately.
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

    async def name_companies(
        self, count: int, names: dict[int, str] | None = None,
    ) -> dict[int, str]:
        """Give each contestant company a readable name.

        OpenTTD leaves companies as "Unnamed", which makes a leaderboard row
        unable to say who played and the company_name column in the result record
        useless. Generated names look like 'jade-heron-4f2a'.

        Args:
            count: How many companies to name, starting from company 0.
            names: Explicit names by company_id, overriding the generated one.
                Lets a contestant choose their own.

        Returns:
            The name applied per company_id. Companies that failed to rename are
            omitted rather than reported optimistically.
        """
        supplied = names or {}
        applied: dict[int, str] = {}
        for company_id in range(count):
            name = supplied.get(company_id) or generate_company_name()
            result = await self.admin_client.send_gamescript(
                "rename_company", {"company_id": company_id, "name": name}, timeout=10.0,
            )
            if result.get("success"):
                applied[company_id] = name
                # Reflect it immediately so a snapshot taken before the next GS
                # refresh does not still say "Unnamed".
                company = self.world.companies.get(company_id)
                if company is not None:
                    company.name = name
            else:
                logger.warning(
                    "Could not name company %d in session %s: %s",
                    company_id, self.session_id, result.get("error", "unknown"),
                )
        if applied:
            logger.info(
                "Named %d company(ies) for session %s: %s",
                len(applied), self.session_id,
                ", ".join(f"{cid}={name}" for cid, name in sorted(applied.items())),
            )
        return applied

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

        if mode == "stepped":
            # No task: stepped mode runs no loop on the server. The contestant drives
            # each step, and the game stays paused in between so deliberation costs
            # nothing. Starting a loop here would move the world underneath a policy
            # that is still thinking, which is the whole thing stepping avoids.
            logger.info(
                "Session %s is stepped: no server loop, the contestant drives each step",
                self.session_id,
            )
            return

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

    def _record_eviction(self, company_id: int) -> None:
        """Record that a company was dropped from the step barrier for going silent.

        Recorded rather than merely logged: a reader comparing this run to a
        single-company one needs to see that a stepper stopped participating, since the
        remaining companies then had the world to themselves.
        """
        self.recorder.record_event(
            self.world.game.game_date,
            "stepper_evicted",
            company_id=company_id,
            detail="did not step within the liveness timeout",
        )

    def _record_client_command(self, command: dict[str, Any]) -> None:
        """Write a command from the game window into the action log.

        The game date comes from nttd's own DATE subscription rather than the packet:
        pyopenttdadmin's frame field is always 0, because it reads the frame from the
        payload buffer after reassigning that buffer to the payload slice.
        """
        self.recorder.record_client_command(command, self.world.game.game_date)
