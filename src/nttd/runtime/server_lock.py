"""One nttd server per sessions directory, enforced before it can touch anything.

A second `nttd server` used to be a kill switch for every live run on the first. The sequence,
from a real log:

    12:09:39  Recovered session 20260825-113321ist-daring-pebble
    12:09:39  Connected to Unnamed Server (OpenTTD 15.3, map 256x256)
    ERROR:    [Errno 48] address already in use
    12:09:40  Final save captured: save/final.sav
    12:09:45  Session ... stopped (reason=nttd_shutdown)

uvicorn runs the application's startup hooks BEFORE it binds its socket. So the second server
adopted a session belonging to the first, discovered the port was taken, and took the ordinary
shutdown path out, which stops every session it had adopted. A run at day 189 of 366 ended
because a second process failed to start.

**The port is the wrong thing to protect.** Two servers on different ports and one sessions
directory are just as destructive: both would recover the same OpenTTD processes and either
could stop them. What must be exclusive is the DIRECTORY, so that is what this locks.

**flock rather than a pid file.** A pid file survives the process that wrote it, so a crashed
server leaves a lock nothing will clear and the next start needs a human. An flock is held by
the file description and the kernel drops it when the process dies, however it dies. There is
no stale state to reap and no `--force` to document.

Acquired before `recover_orphans` and released after `shutdown_all`, which is the whole window
in which a server can adopt or stop somebody else's session.
"""

from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

# Inside the directory it protects, so a second sessions directory is a second server and
# needs no configuration to say so.
LOCK_NAME = ".server.lock"


class ServerLock:
    """An exclusive claim on one sessions directory, for as long as the process lives."""

    def __init__(self, sessions_dir: Path | str) -> None:
        self._dir = Path(sessions_dir)
        self._path = self._dir / LOCK_NAME
        self._fd: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    def holder(self) -> int | None:
        """The pid recorded in the lock file, or None when it is free or unreadable.

        For a MESSAGE, not for a decision. The pid is what the last holder wrote and a file
        can outlive it; whether the lock is actually held is answered by trying to take it.
        """
        try:
            written = self._path.read_text().strip()
        except OSError:
            return None
        return int(written) if written.isdigit() else None

    def acquire(self) -> None:
        """Take the lock, or raise RuntimeError naming what to do about it.

        Raised rather than returned false. The caller is a startup path and the only correct
        response is to stop before touching a session, so an ignorable return value is the
        wrong shape: the previous version of this bug was exactly a failure that carried on.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        # Opened without truncating, so a failed attempt cannot erase the holder's own pid
        # from the file it is holding.
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as taken:
            os.close(fd)
            other = self.holder()
            raise RuntimeError(
                f"another nttd server is already using {self._dir} "
                f"(pid {other if other is not None else 'unknown'}). "
                "Two servers on one sessions directory would both adopt the same OpenTTD "
                "processes and either could stop the other's runs, so this one is not "
                "starting. Stop that server, or point this one somewhere else with "
                "NTTD_SESSIONS_DIR."
            ) from taken

        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)
        self._fd = fd
        logger.info("Holding %s for pid %d", self._path, os.getpid())

    def release(self) -> None:
        """Give the lock up. Safe to call when it was never held."""
        if self._fd is None:
            return
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None

    def __enter__(self) -> ServerLock:
        self.acquire()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.release()
