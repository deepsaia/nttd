"""The monitor server: localhost bound, standard library only.

    nttd monitor

Deliberately not part of the API server. The monitor reads session directories from disk
and needs nothing from the running game, so it works on an ended session, on a session
whose server has already exited, and on a copy of a session directory from another
machine. Bolting it onto the API would have tied a reading tool to a running process for
no gain, and would have put a browser facing page inside the surface contestants
authenticate against.

Bound to the loopback address by default. This page carries a whole run's telemetry and
has no authentication, so it is not something to expose without meaning to.
"""

from __future__ import annotations

import logging
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from nttd.monitor.registry import SessionRegistry
from nttd.monitor.request_handler import MonitorHandler
from nttd.monitor.sentry import Sentry
from nttd.monitor.terrain_png import TerrainPng
from nttd.monitor.watcher import Watcher

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4281
DEFAULT_HOST = "127.0.0.1"

# How often the sentry re-reads every live session. Frequent enough that a stall is
# caught within a step or two of the threshold, rare enough to stay invisible next to the
# game itself.
SWEEP_SECONDS = 60


class MonitorServer(ThreadingHTTPServer):
    """A server carrying the configuration its handlers read."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        registry: SessionRegistry,
        session_limit: int,
    ) -> None:
        super().__init__(address, MonitorHandler)
        self.registry = registry
        self.session_limit = session_limit
        # What the /live stream watches: session writes, and edits to the monitor's own source.
        self.watcher = Watcher(registry.root)
        self._terrain: dict[str, tuple[int, Any]] = {}
        self._terrain_lock = threading.Lock()

    def terrain(self, session_id: str) -> tuple[bytes, int, int, int, int] | None:
        """The session's terrain raster, encoded once and kept.

        Cached because the page asks for it twice per view, once to place it and once to
        fetch it, and refreshes itself every ten seconds. The key includes the tile count
        so a terrain delta written mid-session invalidates it rather than serving a stale
        picture forever.

        Threaded server, so the cache is locked. Two tabs opening the same session at once
        is the ordinary case, not a rare one.
        """
        try:
            tiles = self.registry.feed(session_id).tiles()
        except Exception:
            logger.debug("Could not read tiles for %s", session_id, exc_info=True)
            return None
        count = 0 if tiles is None or tiles.is_empty() else len(tiles)
        if not count:
            return None

        with self._terrain_lock:
            cached = self._terrain.get(session_id)
            if cached is not None and cached[0] == count:
                return cached[1]

        rendered = TerrainPng(tiles).encode()
        with self._terrain_lock:
            self._terrain[session_id] = (count, rendered)
        return rendered


def serve(
    sessions_dir: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    session_limit: int = 40,
    base_url: str = "http://127.0.0.1:8000",
    stop_on_anomaly: bool = False,
) -> None:
    """Serve the monitor until interrupted."""
    registry = SessionRegistry(sessions_dir)
    server = MonitorServer((host, port), registry, session_limit)

    sentry = Sentry(registry, base_url=base_url, armed=stop_on_anomaly)
    stopping = threading.Event()
    watcher = threading.Thread(
        target=_sweep_forever, args=(sentry, stopping), daemon=True,
    )
    watcher.start()

    logger.info("Monitor reading sessions from %s", registry.root)
    logger.info("Monitor serving http://%s:%d", host, port)
    if stop_on_anomaly:
        logger.warning(
            "Armed: a live session tripping a bad rule will be stopped through %s",
            base_url,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Monitor stopped")
    finally:
        stopping.set()
        server.server_close()


def _sweep_forever(sentry: Sentry, stopping: threading.Event) -> None:
    """Run the sentry until the server shuts down.

    Every sweep is wrapped: this thread outliving a transient read error matters more
    than any single sweep succeeding, and a dead watcher thread is silent.
    """
    while not stopping.wait(SWEEP_SECONDS):
        try:
            sentry.sweep()
        except Exception:
            logger.debug("Sentry sweep failed", exc_info=True)
