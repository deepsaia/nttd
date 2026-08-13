"""The HTTP handler: two routes, both returning a whole page.

A top level class rather than one defined inside the serve function, so it can be
imported and exercised directly. It reads its configuration from ``self.server``, which
``ThreadingHTTPServer`` sets on every handler instance.

Any exception becomes a rendered error page rather than a stack trace and a dead tab. The
data underneath is being written by another process, so a read can fail for reasons that
have nothing to do with this code, and the next refresh usually succeeds.
"""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from nttd.monitor import page

logger = logging.getLogger(__name__)

# The map's base image lives on its own route so the browser caches it across the page's
# ten second refresh. Terrain is captured once at session start and barely changes.
TERRAIN_PATH = "/terrain.png"


class MonitorHandler(BaseHTTPRequestHandler):
    """Serves the index and the per session view."""

    server_version = "nttd-monitor"

    def do_GET(self) -> None:  # noqa: N802 - the name is fixed by the base class
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        query = parse_qs(parsed.query)
        session_id = (query.get("session") or [None])[0]

        if parsed.path == TERRAIN_PATH:
            self._serve_terrain(session_id)
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
