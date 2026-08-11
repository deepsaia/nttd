"""Stopping a live session that has gone wrong, when explicitly asked to.

Off unless ``--stop-on-anomaly`` is given. A false positive costs a run that was merely
pausing, and on a two hour tier that is expensive, so arming this is a deliberate act
rather than a default.

What it stops is the nttd session, through the operator endpoint the CLI's ``session
stop`` uses. It does not touch the contestant's process: nttd does not own it, did not
start it, and killing something it cannot see the state of is not its business. Ending
the session is enough, because the next step call then fails and any sane runner exits.

Only ``bad`` verdicts act. A warning is a thing worth reading, not a thing worth ending a
run over.
"""

from __future__ import annotations

import logging
from typing import Any

from nttd.monitor.registry import SessionRegistry

logger = logging.getLogger(__name__)

_BAD = "bad"


class Sentry:
    """Watches live sessions and stops the ones that trip a bad rule."""

    def __init__(self, registry: SessionRegistry, base_url: str, armed: bool) -> None:
        self._registry = registry
        self._base_url = base_url.rstrip("/")
        self._armed = armed
        self._stopped: set[str] = set()

    def sweep(self) -> list[dict[str, Any]]:
        """Check every live session once. Returns what it acted on."""
        acted: list[dict[str, Any]] = []
        for entry in self._registry.entries():
            meta = entry["meta"]
            session_id = meta["session_id"]
            if not meta["live"] or session_id in self._stopped:
                continue
            worst = [v for v in entry["verdicts"] if v["level"] == _BAD]
            if not worst:
                continue
            verdict = worst[0]
            logger.error(
                "Session %s tripped %s: %s (%s)",
                session_id, verdict["rule"], verdict["detail"], verdict["why_it_matters"],
            )
            if self._armed and self._stop(session_id):
                self._stopped.add(session_id)
                acted.append({"session_id": session_id, "rule": verdict["rule"]})
        return acted

    # ------------------------------------------------------------------

    def _stop(self, session_id: str) -> bool:
        """Ask the running server to stop and archive one session."""
        import requests

        url = f"{self._base_url}/v1/operator/admin/sessions/{session_id}/stop"
        try:
            reply = requests.post(url, timeout=15)
            reply.raise_for_status()
        except Exception:
            logger.warning("Could not stop session %s", session_id, exc_info=True)
            return False
        logger.warning("Stopped session %s because a rule tripped", session_id)
        return True
