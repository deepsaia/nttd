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


class MonitorHandler(BaseHTTPRequestHandler):
    """Serves the index and the per session view."""

    server_version = "nttd-monitor"

    def do_GET(self) -> None:  # noqa: N802 - the name is fixed by the base class
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return

        query = parse_qs(parsed.query)
        session_id = (query.get("session") or [None])[0]
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
                return page.error_page(f"No session {session_id} under {registry.root}")

        feed = registry.feed(session_id)
        meta = feed.meta()
        health = registry.health(feed, meta)
        return page.session_page(entries, feed, meta, health.verdicts())
