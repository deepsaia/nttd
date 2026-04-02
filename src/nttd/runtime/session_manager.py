"""Manages multiple OpenTTD server sessions.

Each session gets its own server process, config directory, and runtime stack.
The SessionManager handles port allocation, process lifecycle, and orphan recovery.
"""

import logging
import os
import socket
from pathlib import Path
from typing import Any

from nttd.db.repositories import session_repo
from nttd.runtime.config_builder import build_session_config
from nttd.runtime.session_runtime import SessionRuntime

logger = logging.getLogger(__name__)


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

    def _allocate_ports(self) -> tuple[int, int]:
        """Find the next available game_port/admin_port pair.

        Game ports use even numbers, admin ports use the next odd number.
        Checks both the runtime registry and actual OS port availability.
        """
        used_ports: set[int] = set()
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
                return game_port, admin_port
            port += 2
            if port > self.port_range_start + 1000:
                raise RuntimeError("No available ports in range")

    def get_runtime(self, session_id: str) -> SessionRuntime | None:
        """Get the runtime for a session, or None if not running."""
        return self.runtimes.get(session_id)

    async def start_session(
        self,
        session_id: str,
        settings: dict[str, str] | None = None,
    ) -> SessionRuntime:
        """Start an OpenTTD server for a session.

        Allocates ports, builds config, spawns the process, connects admin client,
        applies settings, and starts a new game.
        """
        if session_id in self.runtimes:
            raise ValueError(f"Session {session_id} is already running")

        # Allocate ports
        game_port, admin_port = self._allocate_ports()

        # Store ports in DB
        await session_repo.update_session_ports(session_id, game_port, admin_port)

        # Build per-session config directory
        session_dir = self.sessions_dir / session_id
        build_session_config(
            base_config_dir=self.base_config_dir,
            session_dir=session_dir,
            game_port=game_port,
            admin_port=admin_port,
            admin_password=self.admin_password,
        )

        # Create runtime and start server
        runtime = SessionRuntime(
            session_id=session_id,
            game_port=game_port,
            admin_port=admin_port,
            config_dir=session_dir,
        )

        ok = await runtime.start_server(self.openttd_binary, self.admin_password)
        if not ok:
            raise RuntimeError(f"Failed to start OpenTTD for session {session_id}")

        # Store PID and mark active
        pid = runtime.process.pid if runtime.process else 0
        await session_repo.mark_session_active(session_id, pid)

        # Apply settings and start new game
        if settings:
            ai_count = int(settings.get("difficulty.max_no_competitors", "0"))
            await runtime.apply_settings_and_start(settings, ai_count)

        self.runtimes[session_id] = runtime
        logger.info(
            "Session %s started: game_port=%d, admin_port=%d, pid=%s",
            session_id, game_port, admin_port, pid,
        )
        return runtime

    async def stop_session(self, session_id: str, end_reason: str = "manual") -> None:
        """Stop a running session's OpenTTD server."""
        runtime = self.runtimes.pop(session_id, None)
        if runtime:
            await runtime.shutdown()

        await session_repo.end_session(session_id, end_reason=end_reason)
        await session_repo.update_session_pid(session_id, None)
        logger.info("Session %s stopped (reason=%s)", session_id, end_reason)

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
