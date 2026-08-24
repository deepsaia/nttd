"""Runs OpenTTD headless for verification, either on a save or on a fresh seed.

Both world-regeneration and score-recomputation need the same awkward setup, and getting
it wrong fails in ways that look like something else. Two constraints, both established
by probing rather than by reading:

**The config directory must contain the GameScript.** A config file in ``/tmp`` made
OpenTTD report *"The savegame has a GameScript by the name 'nttd GameScript' ... which is
no longer available. This game will continue to run without GameScript"* -- and then the
score is simply unreadable. This is a feature rather than a nuisance: the validator
supplies the GameScript **it** trusts, at the digest it can state, so a score is
recomputed by a known script and not by the contestant's copy.

**It must also contain secrets.cfg.** OpenTTD 15.x reads the admin password from there,
and ``_cleanup_config_artifacts`` deletes it when a session stops. Without it the game
port binds and the admin port silently does not, which took a while to spot.

``build_session_config`` already does both, so verification reuses the same builder a
real session uses rather than assembling a config of its own.
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
from pathlib import Path
from typing import Any

from nttd.bridge.admin_client import AdminClient
from nttd.runtime.config_builder import build_session_config

logger = logging.getLogger(__name__)

# The admin password the validator gives its own throwaway server. Not a secret: the
# server exists for seconds, binds loopback, and holds a world anyone may regenerate.
VERIFY_PASSWORD = "verify"

_CONNECT_ATTEMPTS = 40
_CONNECT_INTERVAL_SECONDS = 0.5

# The GameScript needs game ticks to reach the point where it answers, so a ping is
# retried rather than trusted first time.
_GS_ATTEMPTS = 20
_GS_INTERVAL_SECONDS = 1.0


class HeadlessOpenTTD:
    """A throwaway OpenTTD server the validator drives over the admin port."""

    def __init__(
        self,
        openttd_binary: str,
        base_config_dir: Path,
        work_dir: Path,
        game_port: int,
        admin_port: int,
    ) -> None:
        self._binary = openttd_binary
        self._base_config_dir = Path(base_config_dir)
        self._work_dir = Path(work_dir)
        self._game_port = game_port
        self._admin_port = admin_port
        self._process: asyncio.subprocess.Process | None = None
        self._client: AdminClient | None = None
        self._poll: asyncio.Task[None] | None = None
        # Where the game's own output goes, so a refusal to start can be reported.
        self._log_path: Path | None = None
        self._log_file: io.BufferedWriter | None = None

    @property
    def client(self) -> AdminClient:
        """The connected admin client. Only valid inside the context."""
        if self._client is None:
            raise RuntimeError("HeadlessOpenTTD is not running")
        return self._client

    @property
    def work_dir(self) -> Path:
        return self._work_dir

    async def start(
        self,
        settings: dict[str, str] | None = None,
        savegame: Path | None = None,
        map_seed: int | None = None,
        ai_opponents: int = 0,
        agent_companies: int = 0,
    ) -> bool:
        """Build a config directory, spawn the server, and wait for the GameScript.

        Args:
            settings: Effective OpenTTD settings, baked into the config so a
                regenerated world matches the one described.
            savegame: Load this instead of generating. Mutually useful with
                ``map_seed``: pass a save to recompute a score, a seed to regenerate a
                world.
            map_seed: Passed as ``-G``. Only the flag pins generation; the config key
                alone does not.

        Returns:
            Whether the server came up with a responding GameScript.
        """
        build_session_config(
            base_config_dir=self._base_config_dir,
            session_dir=self._work_dir,
            game_port=self._game_port,
            admin_port=self._admin_port,
            admin_password=VERIFY_PASSWORD,
            settings=settings,
            ai_opponents=ai_opponents,
            agent_companies=agent_companies,
        )

        argv = [self._binary, "-D", "-c", str(self._work_dir / "openttd.cfg")]
        if map_seed is not None:
            argv += ["-G", str(map_seed)]
        if savegame is not None:
            argv += ["-g", str(savegame)]

        logger.info("Verification server: %s", " ".join(argv))
        # Kept, not discarded. Both streams went to DEVNULL, so an OpenTTD that refused to
        # start took its reason with it and every failure arrived as the same sentence:
        # "could not reload the savegame with a responding GameScript". Measured on a CI
        # runner, that sentence was hiding `exited with code 1` from a game that never got as
        # far as opening its admin port, and there was nothing anywhere to say why.
        #
        # A file rather than a pipe. Nothing reads this until the process is over, and a pipe
        # nobody drains fills its buffer and blocks the very process being diagnosed.
        self._log_path = self._work_dir / "openttd.log"
        self._log_file = self._log_path.open("wb")
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=self._log_file,
            stderr=asyncio.subprocess.STDOUT,
        )

        if not await self._connect():
            return False
        return await self._wait_for_gamescript()

    async def _connect(self) -> bool:
        """Poll the admin port until it answers or the process dies."""
        client = AdminClient(host="127.0.0.1", port=self._admin_port)
        for _ in range(_CONNECT_ATTEMPTS):
            if self._process is not None and self._process.returncode is not None:
                logger.error(
                    "Verification server exited with code %s. What it said:\n%s",
                    self._process.returncode, self._said(),
                )
                return False
            if await client.connect(password=VERIFY_PASSWORD, name="nttd-verify"):
                self._client = client
                # Without this every GameScript call times out, which reads as a
                # broken server rather than a missing reader.
                self._poll = asyncio.create_task(client.poll_loop())
                await client.subscribe_defaults()
                return True
            await asyncio.sleep(_CONNECT_INTERVAL_SECONDS)

        logger.error("Verification server never opened admin port %d", self._admin_port)
        return False

    def _said(self) -> str:
        """What OpenTTD printed before it gave up, or a note that it printed nothing.

        The tail rather than the whole thing: the reason a game refuses to start is its last
        line, and the lines before it are the base sets it loaded.
        """
        if self._log_file is not None and not self._log_file.closed:
            self._log_file.flush()
        if self._log_path is None or not self._log_path.exists():
            return "  (nothing was captured)"
        said = self._log_path.read_text(errors="replace").strip()
        if not said:
            return "  (it printed nothing at all)"
        return "\n".join(f"  {line}" for line in said.splitlines()[-15:])

    async def _wait_for_gamescript(self) -> bool:
        """Retry a ping until the GameScript answers."""
        for _ in range(_GS_ATTEMPTS):
            reply = await self.client.send_gamescript("ping")
            if reply.get("success"):
                return True
            await asyncio.sleep(_GS_INTERVAL_SECONDS)

        logger.error(
            "GameScript never answered on the verification server. Its config "
            "directory must contain the game/ symlink, or OpenTTD runs without it. "
            "What the game said:\n%s",
            self._said(),
        )
        return False

    async def query(self, action: str, params: dict[str, Any] | None = None,
                    timeout: float = 60.0) -> dict[str, Any]:
        """Run one read-only GameScript query."""
        return await self.client.send_gamescript(action, params or {}, timeout=timeout)

    async def stop(self, keep_work_dir: bool = False) -> None:
        """Disconnect, kill the server, and remove the throwaway config directory."""
        if self._poll is not None and not self._poll.done():
            self._poll.cancel()
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                logger.debug("Verification client disconnect failed")
        if self._process is not None and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
        # After the process is gone, so nothing is still writing to it.
        if self._log_file is not None and not self._log_file.closed:
            self._log_file.close()
        if not keep_work_dir and self._work_dir.exists():
            shutil.rmtree(self._work_dir, ignore_errors=True)
