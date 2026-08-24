"""The HTTP handler: two GET routes returning a whole page, and one POST that deletes.

A top level class rather than one defined inside the serve function, so it can be
imported and exercised directly. It reads its configuration from ``self.server``, which
``ThreadingHTTPServer`` sets on every handler instance.

Any exception becomes a rendered error page rather than a stack trace and a dead tab. The
data underneath is being written by another process, so a read can fail for reasons that
have nothing to do with this code, and the next refresh usually succeeds.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from nttd.monitor import assets, page
from nttd.store import session_paths, session_remover

logger = logging.getLogger(__name__)

# The map's base image lives on its own route so the browser caches it across the page's
# ten second refresh. Terrain is captured once at session start and barely changes.
TERRAIN_PATH = "/terrain.png"
FAVICON_PATH = "/favicon.svg"

# The only route that mutates anything, and the only one that accepts POST.
DELETE_PATH = "/delete"

# Stopping needs the API, which is the one thing the monitor otherwise does without. It
# reads session directories from disk, so it works on a finished run, on a run whose server
# has already exited, and on a copy of a directory from another machine. That property is
# kept: the button only appears for a session that is still live, and if the API cannot be
# reached the reply says so rather than pretending the run was stopped.
STOP_PATH = "/stop"
API_URL = os.environ.get("NTTD_API_URL", "http://127.0.0.1:8000")

# The event stream the page listens on instead of reloading on a timer.
LIVE_PATH = "/live"

# How often the stream checks the fingerprints. Fast enough to feel immediate on a file save,
# and each check is a handful of scandir calls rather than any parsing.
WATCH_INTERVAL_SECONDS = 0.5

# A comment sent down an idle stream so a proxy or a sleeping laptop does not drop it.
KEEPALIVE_SECONDS = 20.0


class SessionIsRunningError(RuntimeError):
    """Deleting a session that is still being written to would strand its recorder."""


class MonitorHandler(BaseHTTPRequestHandler):
    """Serves the index and the per session view."""

    server_version = "nttd-monitor"

    def do_GET(self) -> None:  # noqa: N802 - the name is fixed by the base class
        parsed = urlparse(self.path)
        if parsed.path in (FAVICON_PATH, "/favicon.ico"):
            # Both paths, because the page asks for the .svg and a browser asks for the .ico
            # on its own whether or not it was told to. Answering the same SVG to both beats
            # answering 204 to one of them and having the tab fall back to a blank sheet.
            self._serve_favicon()
            return

        query = parse_qs(parsed.query)
        session_id = (query.get("session") or [None])[0]

        if parsed.path == TERRAIN_PATH:
            self._serve_terrain(session_id)
            return
        if parsed.path == LIVE_PATH:
            self._serve_live()
            return
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        try:
            body = self._render(session_id).encode("utf-8")
        except Exception as error:
            logger.debug("Render failed", exc_info=True)
            body = page.error_page(repr(error)).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - the name is fixed by the base class
        """The one route that changes anything: deleting a session's files.

        POST rather than a link, so no prefetch, crawler or accidental refresh can destroy a
        recording, and it answers with a redirect so the browser reloads the list rather than
        leaving a resubmittable form in the history.
        """
        route = urlparse(self.path).path
        if route not in (DELETE_PATH, STOP_PATH):
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8")) if length else {}
        session_id = (form.get("session") or [""])[0]

        if route == STOP_PATH:
            self._answer_stop(session_id)
            return

        try:
            self._delete(session_id)
        except session_paths.InvalidSessionIdError:
            logger.warning("Refused to delete %r: not a session id", session_id)
            self.send_error(400, "not a session id")
            return
        except SessionIsRunningError:
            # Its own answer, because "still running" is not a fault. This used to fall
            # through to the 500 below and read as a broken monitor rather than as a run
            # that has not finished.
            logger.info("Refused to delete %s: still running", session_id)
            self.send_error(
                409,
                "still running: stop it first with `nttd session stop -s <session>`",
            )
            return
        except Exception:
            logger.exception("Failed to delete session %s", session_id)
            self.send_error(500, "could not delete the session")
            return

        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _answer_stop(self, session_id: str) -> None:
        """Ask the API to end a running session, and report honestly if it cannot."""
        try:
            session_paths.validate_session_id(session_id)
        except session_paths.InvalidSessionIdError:
            self.send_error(400, "not a session id")
            return

        try:
            self._stop(session_id)
        except Exception as failure:
            logger.warning("Could not stop %s: %r", session_id, failure)
            self.send_error(
                502,
                f"could not reach nttd at {API_URL} to stop it. Is `nttd server` running?",
            )
            return

        self.send_response(303)
        self.send_header("Location", f"/?session={session_id}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _stop(self, session_id: str) -> None:
        """End the run through the operator route, which is what owns the game process."""
        import urllib.request  # noqa: PLC0415

        request = urllib.request.Request(
            f"{API_URL}/v1/operator/admin/sessions/{session_id}/stop",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as reply:  # noqa: S310
            reply.read()

    def _delete(self, session_id: str) -> None:
        """Remove one session, refusing while it is still being written.

        The liveness check is here rather than in the remover because only the registry knows
        how recently a session wrote. Deleting the directory under a running recorder would
        leave the server flushing into a path that no longer exists.
        """
        if not session_id:
            raise session_paths.InvalidSessionIdError("no session given")
        # Validate BEFORE asking whether it is live. is_live cannot read a nonsense id, and it
        # errs towards "live", so checking it first turned "../escape" into a 500 "still
        # running" instead of a 400 "not a session id".
        session_paths.validate_session_id(session_id)
        if self.server.registry.is_live(session_id):
            raise SessionIsRunningError(session_id)
        session_remover.remove_session(session_id, self.server.registry.root)

    def _serve_live(self) -> None:
        """Hold the connection open and say when something has actually changed.

        Server-sent events rather than a meta refresh. The browser makes one request and then
        waits, so an idle dashboard costs nothing and a written snapshot appears at once instead
        of up to a refresh interval later.

        A code edit is answered by re-executing the process. The page is rendered from these
        modules, so reloading the browser against a server still running the old import shows
        the old page, which reads as the edit not working. Reloading modules in place cannot be
        done honestly here either: the running server holds this handler CLASS, so a reloaded
        module would not be the one serving requests.
        """
        watcher = self.server.watcher
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self._push("hello", "connected")
        except OSError:
            return

        data = watcher.data_revision()
        code = watcher.code_revision()
        last_beat = time.monotonic()
        while True:
            time.sleep(WATCH_INTERVAL_SECONDS)
            fresh_code = watcher.code_revision()
            if fresh_code != code:
                logger.info("Monitor source changed; restarting to serve the new code")
                self._push("code", "reloading")
                self._restart()
                return
            fresh_data = watcher.data_revision()
            now = time.monotonic()
            if fresh_data != data:
                data = fresh_data
                if not self._push("data", "changed"):
                    return
                last_beat = now
            elif now - last_beat >= KEEPALIVE_SECONDS:
                if not self._push("beat", "."):
                    return
                last_beat = now

    def _push(self, event: str, payload: str) -> bool:
        """Send one event. False once the browser has gone, which is not an error."""
        try:
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
            self.wfile.flush()
        except OSError:
            return False
        return True

    def _restart(self) -> None:
        """Re-exec this process so an edited module is actually imported.

        os.execv replaces the process, so there is nothing to tear down and no second server
        racing for the port. Open streams die with it; every page reconnects, because an
        EventSource retries on its own.
        """
        try:
            self.wfile.flush()
        except OSError:
            pass
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Quiet by default. One line per browser refresh, every ten seconds, for every
        open tab, would bury whatever the operator is actually watching."""
        logger.debug("%s - %s", self.address_string(), format % args)

    # ------------------------------------------------------------------

    def _serve_terrain(self, session_id: str | None) -> None:
        """The terrain raster for one session, or 404 when it recorded none."""
        if not session_id:
            self.send_error(404)
            return
        rendered = self.server.terrain(session_id)
        if rendered is None:
            self.send_error(404)
            return
        body = rendered[0]
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        # Immutable for the life of the page: the session's scan does not change, and
        # re-encoding it on every ten second refresh would be pure waste.
        self.send_header("Cache-Control", "max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def _serve_favicon(self) -> None:
        """The tab icon, inline from assets rather than off disk.

        Cached hard: it is a constant, and the page reloads every ten seconds while a run is
        live, so a revalidation per reload would be a request per icon for nothing.
        """
        body = assets.FAVICON_SVG.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _render(self, session_id: str | None) -> str:
        registry = self.server.registry
        entries = registry.entries(limit=self.server.session_limit)
        if session_id is None:
            return page.index_page(entries)

        known = {entry["meta"]["session_id"] for entry in entries}
        if session_id not in known:
            # Asked for by name but outside the listed window, or gone. Load it directly
            # rather than pretending it does not exist.
            try:
                entries = [registry.entry(session_id), *entries]
            except Exception:
                # Fall back to the index rather than an error page. A stale link, a bookmark
                # from a deleted session, or a refresh after a cleanup all landed on a dead
                # end that offered nowhere to go; the list of what does exist is both more
                # useful and what the reader wanted anyway.
                logger.debug("No session %s; showing the index", session_id, exc_info=True)
                return page.index_page(entries)

        feed = registry.feed(session_id)
        meta = feed.meta()
        health = registry.health(feed, meta)
        return page.session_page(
            entries, feed, meta, health.verdicts(),
            terrain=self._terrain_placement(session_id),
        )

    def _terrain_placement(self, session_id: str) -> dict[str, Any] | None:
        """Where the terrain image sits on the map, or None if there is none.

        Tiles run from 1 to the map size less two, so the image is offset by a tile. Drawn
        at the origin it would sit a tile away from the stations plotted over it, which is
        the kind of error that looks like a rendering quirk rather than a bug.
        """
        rendered = self.server.terrain(session_id)
        if rendered is None:
            return None
        _png, x0, y0, width, height = rendered
        return {
            "url": f"{TERRAIN_PATH}?session={session_id}",
            "x": x0, "y": y0, "width": width, "height": height,
        }
