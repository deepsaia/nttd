"""Captures the savegame a verifier replays, and confirms it actually landed.

A result says a company scored 812. The savegame is what lets somebody else reload the
world and get 812 back, so it is the single most load-bearing artifact in a submission:
without it a score is self-reported and nothing more.

It was previously captured on a timer inside the real-time loop, by a fire-and-forget
``asyncio.create_task`` wrapped in a bare except that logged at debug. Three
consequences: a stepped run produced no save at all because that loop never runs, a
manually stopped run produced none either, and nothing anywhere checked that a save had
been written. This runs at session end instead, in every mode, and confirms the file.

Confirmation needs both halves. OpenTTD's rcon replies with a success line, but that
reply arrives *before* the bytes are flushed: polling 40ms after a confirmed save found
the file present at 0 bytes, settling at 25 KB shortly after.

The second half is ``openttd -q``, not a size check. Waiting for the size to stop
changing is a heuristic, and a test of a file written in two chunks with a pause between
them caught it returning a 100-byte partial save as settled. ``-q`` is an actual
integrity check, measured: exit 0 on a complete save, exit 1 on one truncated to 40%,
on an empty file, and on a missing one. A save that cannot be inspected cannot be
reloaded, which is the only property that matters here.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# What OpenTTD appends to the name given to `save`.
SAVE_EXTENSION = ".sav"

# The name every session's final save takes, so a verifier need not guess.
FINAL_SAVE_NAME = "final"

_SUCCESS_MARKER = "successfully saved"

_DEFAULT_TIMEOUT_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 0.2

# How long `openttd -q` gets to inspect one savegame. It exits immediately in practice.
_INSPECT_TIMEOUT_SECONDS = 20.0


class FinalSaveCapture:
    """Asks OpenTTD to save, then waits until the file is really on disk."""

    def __init__(
        self,
        client: Any,
        save_dir: Path,
        openttd_binary: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """
        Args:
            client: A connected AdminClient. rcon goes over this rather than the HTTP
                route deliberately: the route refuses rcon on a scored session, which
                is every session whose save matters most.
            save_dir: Where OpenTTD writes saves, ``<session>/save``.
            openttd_binary: Used to inspect the save with ``-q``. Without it the check
                falls back to "the file is non-empty", which is weaker: a truncated
                save passes that and then fails to reload.
            timeout: How long to wait for a complete, inspectable save.
        """
        self._client = client
        self._save_dir = Path(save_dir)
        self._openttd_binary = openttd_binary
        self._timeout = timeout

    async def capture(self, name: str = FINAL_SAVE_NAME) -> Path | None:
        """Save the game and return the confirmed path, or None if it did not land.

        None rather than an exception: a session must still stop and write its result
        when the save fails, because a result without a save is a weaker submission but
        an incomplete shutdown is a stuck process. The absence is recorded, so the gap
        is visible rather than silent.
        """
        if not getattr(self._client, "connected", False):
            logger.warning("No admin connection, so no final save was captured")
            return None

        reply = await self._send(name)
        if reply is None:
            return None
        if not _reports_success(reply):
            logger.warning(
                "OpenTTD did not confirm the save of %r; rcon said: %s", name, reply,
            )
            return None

        path = self._save_dir / f"{name}{SAVE_EXTENSION}"
        if not await self._wait_until_complete(path):
            logger.warning(
                "OpenTTD confirmed saving %r but %s was not a complete savegame "
                "within %.0fs",
                name, path, self._timeout,
            )
            return None

        logger.info("Final save captured: %s (%d bytes)", path, path.stat().st_size)
        return path

    async def _send(self, name: str) -> list[str] | None:
        """Issue the rcon save, returning its reply lines or None if it failed."""
        try:
            return await self._client.send_rcon(f"save {name}")
        except Exception:
            logger.exception("Final save rcon failed")
            return None

    async def _wait_until_complete(self, path: Path) -> bool:
        """Wait until the file is a savegame OpenTTD can actually read."""
        waited = 0.0
        while waited < self._timeout:
            if path.exists() and path.stat().st_size > 0 and await self._inspect(path):
                return True
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            waited += _POLL_INTERVAL_SECONDS
        return False

    async def _inspect(self, path: Path) -> bool:
        """Whether ``openttd -q`` can read the savegame.

        Without a binary this degrades to "the file is non-empty", which the caller
        has already established. Weaker, and said so at construction, but a missing
        binary should not turn a good save into no save.
        """
        if not self._openttd_binary:
            return True
        try:
            process = await asyncio.create_subprocess_exec(
                self._openttd_binary, "-q", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=_INSPECT_TIMEOUT_SECONDS)
        except (OSError, TimeoutError, asyncio.TimeoutError):
            logger.debug("Could not inspect %s with openttd -q", path)
            return False
        return process.returncode == 0


def _reports_success(reply: list[str]) -> bool:
    """Whether OpenTTD's rcon reply says the save worked.

    Matched on the message rather than on the call returning: a timed-out rcon returns
    an empty list, and an empty list is not a save.
    """
    return any(_SUCCESS_MARKER in str(line).lower() for line in reply)
