"""Manages multiple OpenTTD server sessions.

Each session gets its own server process, config directory, and runtime stack.
The SessionManager handles port allocation, process lifecycle, and orphan recovery.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nttd.runtime.orchestrator import Orchestrator

from nttd.analysis.score import rank_companies
from nttd.config.benchmark_profile import dimensions_from_settings
from nttd.config.fairness import from_settings as fairness_from_settings
from nttd.config.scenario_config import (
    BankruptcyConfig,
    CargoThresholdConfig,
    EndConditionsConfig,
    GameDateLimitConfig,
    MaxHeartbeatsConfig,
    RevenueThresholdConfig,
    TimeLimitConfig,
)
from nttd.config.task_instance import compute_task_instance
from nttd.runtime.action_budget import from_fairness as budget_from_fairness
from nttd.runtime.config_builder import build_session_config
from nttd.runtime.participant_registry import ParticipantRegistry
from nttd.runtime.session_runtime import SessionRuntime
from nttd.store.repositories import session_repo
from nttd.store.result_writer import ResultWriter

logger = logging.getLogger(__name__)


def _apply_step_size(runtime: SessionRuntime, settings: dict[str, str]) -> None:
    """Give the orchestrator the scenario's game-days-per-step.

    Without this the orchestrator keeps its 30-day default, so a scenario asking for
    15 silently got 30: every step covered twice the intended world and the run
    reached its horizon in half the steps. Applied on recovery too, since a restart
    that reverted the step size would change the task mid-run.
    """
    raw = settings.get("_heartbeat_interval_days")
    if raw in (None, ""):
        return
    try:
        runtime.orchestrator.set_heartbeat_interval(int(raw))
    except (TypeError, ValueError):
        logger.warning("Ignoring non-integer _heartbeat_interval_days=%r", raw)


def _port_is_free(port: int) -> bool:
    """Check if a TCP port is available by attempting to bind to it."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


class SessionManager:
    """Manages the lifecycle of multiple OpenTTD server sessions."""

    def __init__(
        self,
        openttd_binary: str,
        base_config_dir: Path,
        sessions_dir: Path,
        admin_password: str = "nttd",
        port_range_start: int = 4000,
    ) -> None:
        self.openttd_binary = openttd_binary
        self.base_config_dir = base_config_dir
        self.sessions_dir = sessions_dir
        self.admin_password = admin_password
        self.port_range_start = port_range_start
        self.runtimes: dict[str, SessionRuntime] = {}
        # Ports handed out but not yet backed by a registered runtime. See
        # _allocate_ports: the gap between the two is seconds long.
        self._reserved_ports: set[int] = set()

    def _allocate_ports(self) -> tuple[int, int]:
        """Reserve the next free game_port/admin_port pair.

        Game ports use even numbers, admin ports use the next odd number.

        The pair is reserved here, not when the runtime is registered. A session is
        only added to ``self.runtimes`` after its server has spawned, which takes
        about eight seconds, and ``start_session`` awaits repeatedly in between --
        so two concurrent starts both read an empty registry and both took port
        4000. Verified: four concurrent starts were all handed 4000.

        ``_port_is_free`` cannot close that window either, since it binds and
        releases immediately rather than holding the port.

        This matters for evolution strategies, which run a population of episodes
        concurrently and would otherwise have every candidate collide on one port.
        """
        used_ports: set[int] = set(self._reserved_ports)
        for rt in self.runtimes.values():
            used_ports.add(rt.game_port)
            used_ports.add(rt.admin_port)

        port = self.port_range_start
        while True:
            game_port = port
            admin_port = port + 1
            if (
                game_port not in used_ports
                and admin_port not in used_ports
                and _port_is_free(game_port)
                and _port_is_free(admin_port)
            ):
                # Reserved before returning, with no await in between, so a
                # concurrent caller cannot observe the pair as free.
                self._reserved_ports.update((game_port, admin_port))
                return game_port, admin_port
            port += 2
            if port > self.port_range_start + 1000:
                raise RuntimeError("No available ports in range")

    def _release_ports(self, game_port: int, admin_port: int) -> None:
        """Return a reserved pair to the pool.

        Called when a session ends and when a start fails partway, so a failed
        spawn does not leak its ports for the life of the process.
        """
        self._reserved_ports.discard(game_port)
        self._reserved_ports.discard(admin_port)

    def get_runtime(self, session_id: str) -> SessionRuntime | None:
        """Get the runtime for a session, or None if not running."""
        return self.runtimes.get(session_id)

    async def start_session(
        self,
        session_id: str,
        settings: dict[str, str] | None = None,
        ai_opponents: int = 0,
        agent_companies: int = 0,
        company_names: dict[int, str] | None = None,
    ) -> SessionRuntime:
        """Start an OpenTTD server for a session.

        Allocates ports, builds config, spawns the process, connects admin client,
        applies settings, and starts a new game.

        Args:
            company_names: Names by company_id. Any contestant company omitted
                gets a generated name, since OpenTTD's default "Unnamed" leaves a
                result row unable to identify who played.
        """
        if session_id in self.runtimes:
            raise ValueError(f"Session {session_id} is already running")

        # Allocate ports
        game_port, admin_port = self._allocate_ports()

        # Store ports in DB
        await session_repo.update_session_ports(session_id, game_port, admin_port)

        # Resolve AI counts
        effective_settings = settings or {}
        ai_count_from_settings = int(effective_settings.get("difficulty.max_no_competitors", "0"))
        ai_count = max(ai_opponents, ai_count_from_settings)

        # The scenario file this session was created from, recorded at create
        # time. Snapshotted into the session dir so a later edit to the source
        # cannot change what a completed run claims to have played.
        session_row = await session_repo.get_session_by_id(session_id)
        scenario_path = (session_row or {}).get("meta", {}).get("config_path")

        # Build per-session config directory — settings baked into openttd.cfg
        # so the initial map generation uses them (no newgame RCON needed).
        session_dir = self.sessions_dir / session_id
        build_session_config(
            base_config_dir=self.base_config_dir,
            session_dir=session_dir,
            game_port=game_port,
            admin_port=admin_port,
            admin_password=self.admin_password,
            settings=effective_settings,
            ai_opponents=ai_count,
            agent_companies=agent_companies,
            scenario_path=scenario_path,
        )

        # Map seed: the cfg key is written for the record, but only the -G flag
        # actually pins generation, so it is threaded to the spawn separately.
        raw_seed = effective_settings.get("_map_seed")
        map_seed = int(raw_seed) if raw_seed not in (None, "") else None

        # Task instance identity -- computed from the settings that define the
        # problem, so a result stays traceable to the exact world and rules.
        task = compute_task_instance(
            effective_settings,
            scenario_id=effective_settings.get("_scenario_id", "unknown"),
        )
        logger.info(
            "Session %s task instance: task_id=%s scenario=%s seed=%s",
            session_id, task.task_id, task.scenario_id, task.seed,
        )

        # Persist effective settings to DB for reproducibility
        persist_settings = dict(effective_settings)
        persist_settings["_agent_companies"] = str(agent_companies)
        persist_settings["_ai_opponents"] = str(ai_count)
        persist_settings["_task_id"] = task.task_id
        persist_settings["_settings_digest"] = task.settings_digest
        await session_repo.upsert_settings(session_id, persist_settings)

        # Create runtime and start server
        runtime = SessionRuntime(
            session_id=session_id,
            game_port=game_port,
            admin_port=admin_port,
            config_dir=session_dir,
        )
        runtime.map_seed = map_seed
        runtime.task_instance = task
        # Lock a scored session before the server is up, so the window between
        # spawn and lock cannot be used.
        runtime.scored_lock.scored = effective_settings.get("_scored") == "1"
        runtime.fairness = fairness_from_settings(effective_settings)
        runtime.action_budget = budget_from_fairness(runtime.fairness)
        runtime.dimensions = dimensions_from_settings(effective_settings)
        _apply_step_size(runtime, effective_settings)
        if runtime.scored_lock.scored:
            logger.info(
                "Session %s is SCORED: game-mutating operator operations are refused",
                session_id,
            )

        ok = await runtime.start_server(
            self.openttd_binary, self.admin_password, map_seed=map_seed,
        )
        if not ok:
            # Hand the ports back: a failed spawn would otherwise hold them until
            # the process exits, and an ES population of failures would exhaust the
            # range.
            self._release_ports(game_port, admin_port)
            raise RuntimeError(f"Failed to start OpenTTD for session {session_id}")

        # Store PID and mark active
        pid = runtime.process.pid if runtime.process else 0
        await session_repo.mark_session_active(session_id, pid)

        # Start AI companies (no newgame needed — settings already in config)
        await runtime.start_companies(ai_count, agent_companies)

        # Issue one participant token per contestant company. Companies are
        # allocated from 0, and AI opponents occupy the slots after the agent
        # ones, so the first agent_companies ids are the contestant's.
        #
        # Tokens are also written to the session directory because a contestant's
        # agent often runs as a separate process that never saw this response.
        if agent_companies > 0:
            for company_id in range(agent_companies):
                runtime.participants.issue(company_id)
            runtime.participants.write(session_dir)
            await runtime.name_companies(agent_companies, names=company_names)

        # Configure orchestrator from runtime settings
        orch = runtime.orchestrator
        orch._screenshot_interval_seconds = float(
            effective_settings.get("_screenshot_interval_seconds", "60"),
        )
        orch._screenshot_type = effective_settings.get("_screenshot_type", "minimap")
        orch._save_interval_seconds = float(
            effective_settings.get("_save_interval_seconds", "300"),
        )
        snapshot_days = effective_settings.get("_snapshot_interval_days")
        if snapshot_days:
            orch._snapshot_interval_days = int(snapshot_days)

        # Configure end conditions from settings
        self._apply_end_conditions(orch, effective_settings)

        # Register session-level on_end callback to fully stop the session
        async def _on_session_end(reason: str) -> None:
            logger.info("End condition triggered for %s: %s", session_id, reason)
            await self.stop_session(session_id, end_reason=reason)

        orch.on_end.append(_on_session_end)

        # Auto-start the orchestrator loop for snapshot capture
        runtime_mode = effective_settings.get("_runtime_mode", "async_realtime")

        # Capture the run's starting point for the result record. The game date is
        # read after the initial world refresh, so it reflects the generated map.
        runtime.runtime_mode = runtime_mode
        runtime.started_at = time.time()
        runtime.start_game_date = runtime.world.game.game_date

        runtime.start_orchestrator(mode=runtime_mode)

        self.runtimes[session_id] = runtime
        logger.info(
            "Session %s started: game_port=%d, admin_port=%d, pid=%s, mode=%s",
            session_id, game_port, admin_port, pid, runtime_mode,
        )
        return runtime

    async def stop_session(self, session_id: str, end_reason: str = "manual") -> None:
        """Stop a running session's OpenTTD server and clean up transient files.

        Preserves the session's recorded Parquet while removing
        OpenTTD config artifacts (openttd.cfg, secrets.cfg, symlinks, saves).
        """
        runtime = self.runtimes.pop(session_id, None)
        if runtime:
            # Score before shutting down -- the world state is needed, and a
            # failure here must not prevent the process from being stopped.
            try:
                self._write_result(session_id, runtime, end_reason)
            except Exception:
                logger.exception("Session %s: failed to write result record", session_id)
            await runtime.shutdown()
            self._release_ports(runtime.game_port, runtime.admin_port)

        await session_repo.end_session(session_id, end_reason=end_reason)
        await session_repo.update_session_pid(session_id, None)

        # Clean up OpenTTD config artifacts only -- preserve session data
        session_dir = self.sessions_dir / session_id
        if session_dir.exists():
            self._cleanup_config_artifacts(session_dir)

        logger.info("Session %s stopped (reason=%s)", session_id, end_reason)

    def _write_result(
        self, session_id: str, runtime: SessionRuntime, end_reason: str,
    ) -> None:
        """Score the finished session and write its immutable result record."""
        scores = rank_companies(list(runtime.world.companies.values()))
        if not scores:
            logger.warning("Session %s: no active companies to score", session_id)
            return

        # Report the SCORED clock, which starts at the first contestant action,
        # not session provisioning. If no action was ever taken the run has no
        # scored duration, so it reports 0 rather than the provisioning time.
        checker = runtime.orchestrator._end_checker
        clock_start = checker.start_time
        scored_seconds = (time.time() - clock_start) if clock_start else 0.0
        start_date = (
            checker.start_game_date
            if checker.start_game_date is not None
            else runtime.start_game_date
        )

        writer = ResultWriter(self.sessions_dir / session_id)
        writer.write(
            session_id=session_id,
            scores=scores,
            task=runtime.task_instance,
            runtime_mode=runtime.runtime_mode,
            end_reason=end_reason,
            wall_seconds=scored_seconds,
            start_game_date=start_date,
            end_game_date=runtime.world.game.game_date,
            # Action counts come from nttd's own log; model and spend only from
            # what the contestant declared. See runtime/participant_report.py.
            participants=runtime.participant_report.build(
                action_counts=runtime.recorder.action_counts(),
            ),
            gamescript_path=self.base_config_dir / "game" / "nttd-gs" / "main.nut",
            openttd_binary=self.openttd_binary,
            capability=runtime.scored_lock.summary(),
            fairness=runtime.fairness.as_dict(),
            budget=runtime.action_budget.usage(),
            dimensions=runtime.dimensions,
        )

    def _cleanup_config_artifacts(self, session_dir: Path) -> None:
        """Remove OpenTTD config files and symlinks, keep session data.

        Preserves: session.parquet, agents.parquet, _fragments/, *.parquet,
                   save/ (game saves), screenshot/ (minimap captures),
                   openttd.cfg (the provenance record of the world played).

        openttd.cfg is deliberately kept: it is the only complete record of the
        settings the map was generated from, so deleting it would make a scored
        run unverifiable.
        """
        # Participant tokens are credentials, so they do not outlive the session.
        ParticipantRegistry.remove(session_dir)

        # Files created by config_builder or OpenTTD runtime. secrets.cfg is
        # removed because it holds the admin password.
        config_files = [
            "secrets.cfg", "private.cfg",
            "favs.cfg", "hotkeys.cfg", "hs.dat", "windows.cfg",
        ]
        for name in config_files:
            p = session_dir / name
            if p.exists():
                p.unlink()

        # Symlinks to shared dirs (game, ai, baseset, etc.)
        symlink_dirs = ["game", "ai", "baseset", "newgrf", "content_download", "scripts"]
        for name in symlink_dirs:
            p = session_dir / name
            if p.is_symlink():
                p.unlink()

        # Remove transient OpenTTD dirs
        transient_dirs = [
            "scenario", "baseset", "newgrf", "content_download", "social_integration",
        ]
        for name in transient_dirs:
            p = session_dir / name
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)

        # Remove save/ and screenshot/ if they are empty (feature was disabled)
        for name in ["save", "screenshot"]:
            p = session_dir / name
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()

        logger.info("Cleaned up config artifacts in %s", session_dir)

    def _apply_end_conditions(
        self, orch: Orchestrator, settings: dict[str, str],
    ) -> None:
        """Configure end conditions on the orchestrator from _ec_* settings."""
        logic = settings.get("_ec_logic")
        if not logic:
            return

        # EndConditionsConfig enables time_limit by default, which would silently
        # impose a 60-minute cap on a scenario that deliberately set none. Only
        # the conditions actually serialised are enabled here.
        config = EndConditionsConfig(
            logic=logic,
            time_limit=TimeLimitConfig(enabled=False),
        )
        enabled: list[str] = []

        wall_min = settings.get("_ec_wall_minutes")
        if wall_min:
            config.time_limit = TimeLimitConfig(enabled=True, wall_minutes=float(wall_min))
            enabled.append(f"time={wall_min}min")
        end_year = settings.get("_ec_end_year")
        if end_year:
            config.game_date_limit = GameDateLimitConfig(enabled=True, end_year=int(end_year))
            enabled.append(f"year={end_year}")
        revenue = settings.get("_ec_revenue")
        if revenue:
            config.revenue_threshold = RevenueThresholdConfig(enabled=True, total_revenue=int(revenue))
            enabled.append(f"revenue={revenue}")
        cargo = settings.get("_ec_cargo")
        if cargo:
            config.cargo_threshold = CargoThresholdConfig(enabled=True, total_cargo_delivered=int(cargo))
            enabled.append(f"cargo={cargo}")
        beats = settings.get("_ec_max_heartbeats")
        if beats:
            config.max_heartbeats = MaxHeartbeatsConfig(enabled=True, count=int(beats))
            enabled.append(f"steps={beats}")
        if settings.get("_ec_bankruptcy"):
            config.bankruptcy = BankruptcyConfig(enabled=True)
            enabled.append("bankruptcy")

        orch.configure_end_conditions(config)
        logger.info(
            "End conditions applied: logic=%s, %s",
            logic, ", ".join(enabled) if enabled else "none enabled",
        )

    async def recover_orphans(self) -> None:
        """On nttd restart, try to reconnect to still-running OpenTTD servers."""
        active_sessions = await session_repo.get_active_sessions_with_ports()
        for session_data in active_sessions:
            sid = session_data["session_id"]
            pid = session_data.get("pid")
            game_port = session_data.get("game_port")
            admin_port = session_data.get("admin_port")

            if not pid or not game_port or not admin_port:
                logger.warning("Session %s missing port/pid data, marking crashed", sid)
                await session_repo.end_session(sid, end_reason="crashed")
                continue

            # Check if process is still alive
            if not _process_alive(pid):
                logger.warning("Session %s PID %d is dead, marking crashed", sid, pid)
                await session_repo.end_session(sid, end_reason="crashed")
                await session_repo.update_session_pid(sid, None)
                continue

            # Try to reconnect
            session_dir = self.sessions_dir / sid
            runtime = SessionRuntime(
                session_id=sid,
                game_port=game_port,
                admin_port=admin_port,
                config_dir=session_dir,
            )

            # Restore provenance -- the map already exists, so the seed and task
            # identity are a record of what it was generated from, not spawn
            # arguments. Recomputed from the persisted settings so a recovered
            # session still produces a complete result record.
            stored = await session_repo.get_settings(sid) or {}
            raw_seed = stored.get("_map_seed")
            if raw_seed not in (None, ""):
                runtime.map_seed = int(raw_seed)

            # Restore the scored lock and fairness limits BEFORE the session is
            # reachable again. Without this a recovered scored session would run
            # unlocked and unbounded, so an nttd restart would silently turn a
            # scored run into an unprotected one.
            runtime.scored_lock.scored = stored.get("_scored") == "1"
            runtime.fairness = fairness_from_settings(stored)
            runtime.action_budget = budget_from_fairness(runtime.fairness)
            runtime.dimensions = dimensions_from_settings(stored)
            _apply_step_size(runtime, stored)
            if runtime.scored_lock.scored:
                logger.info("Recovered session %s is SCORED: lock restored", sid)
            if stored:
                runtime.task_instance = compute_task_instance(
                    stored,
                    scenario_id=stored.get("_scenario_id", "unknown"),
                )

            # Reload the tokens the session already handed out, so agents that
            # survived the restart keep working instead of getting 401s.
            loaded = runtime.participants.load(session_dir)
            if loaded:
                logger.info("Session %s: restored %d participant token(s)", sid, loaded)

            ok = await runtime.connect_to_existing(self.admin_password)
            if ok:
                self.runtimes[sid] = runtime
                logger.info("Recovered session %s (PID %d)", sid, pid)
            else:
                logger.warning("Session %s: process alive but admin connect failed, marking crashed", sid)
                await session_repo.end_session(sid, end_reason="crashed")
                await session_repo.update_session_pid(sid, None)

    async def shutdown_all(self) -> None:
        """Shut down all running sessions (called on app shutdown)."""
        session_ids = list(self.runtimes.keys())
        for sid in session_ids:
            try:
                await self.stop_session(sid, end_reason="nttd_shutdown")
            except Exception:
                logger.exception("Error shutting down session %s", sid)

    def list_running(self) -> list[dict[str, Any]]:
        """List all currently running sessions with their ports."""
        return [
            {
                "session_id": sid,
                "game_port": rt.game_port,
                "admin_port": rt.admin_port,
                "connected": rt.connected,
                "pid": rt.process.pid if rt.process else None,
            }
            for sid, rt in self.runtimes.items()
        ]


def _process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
