"""Finding the sessions on disk and judging each one.

Kept apart from the pages so the same reading can be used without a browser: the sentry
polls this, and a test can assert on the verdicts without rendering any HTML.

Nothing is cached. A session being watched is a session being written to, so a cache is a
way to show a step that has already been superseded. Reading a handful of small parquet
files per request is cheaper than being wrong.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from nttd.analysis.loader import load_session
from nttd.monitor.health import Health
from nttd.monitor.session_feed import SessionFeed
from nttd.store import session_paths

logger = logging.getLogger(__name__)

# The parquet a session writes. Their newest modification time is how long it has been
# since anything happened, which is the only way to tell a stalled run from a slow one.
_TRACKED = ("snapshots", "actions", "events")

# Silent for an hour with fragments still on disk: whatever was writing is gone. Well past
# any real step, and past a long pause at a breakpoint, so nothing healthy reaches it.
ABANDONED_SECONDS = 3600


class SessionRegistry:
    """Every session in a sessions directory, newest first."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._root = Path(sessions_dir) if sessions_dir else session_paths.sessions_dir()

    @property
    def root(self) -> Path:
        return self._root

    def session_ids(self, limit: int = 40) -> list[str]:
        """The most recently active sessions, newest first.

        Bounded because a long lived machine accumulates them and the index only needs
        the ones somebody might still be looking at. The bound is reported on the page
        rather than applied silently.
        """
        if not self._root.exists():
            return []
        dirs = [d for d in self._root.iterdir() if d.is_dir()]
        dirs.sort(key=_started_at, reverse=True)
        return [d.name for d in dirs[:limit]]

    def entries(self, limit: int = 40) -> list[dict[str, Any]]:
        """One index row per session: what it is and whether it is going wrong.

        A session that cannot be read is skipped with a log line rather than raising. A
        half written fragment or a directory from an older layout must not blank the page
        for every other session.
        """
        rows: list[dict[str, Any]] = []
        for session_id in self.session_ids(limit):
            try:
                rows.append(self.entry(session_id))
            except Exception:
                logger.debug("Skipping unreadable session %s", session_id, exc_info=True)
        return rows

    def entry(self, session_id: str) -> dict[str, Any]:
        """One session's metadata and verdicts, without parsing its whole history."""
        feed = self.feed(session_id)
        meta = feed.meta()
        self._settle_state(meta)
        health = self.health(feed, meta)
        return {
            "meta": meta,
            "health": {"level": health.level(), "summary": health.summary()},
            "verdicts": health.verdicts(),
        }

    def feed(self, session_id: str) -> SessionFeed:
        return SessionFeed(load_session(session_id, sessions_dir=self._root))

    def state_of(self, meta: dict[str, Any]) -> str:
        """Whether a session is running, abandoned, or finished.

        Unmerged fragments alone cannot answer this. A session killed uncleanly leaves its
        fragments behind for good, so it reads as running for as long as the directory
        exists. Sessions from five days earlier were still being reported live, and the
        stall rule then shouted about each of them on every sweep.

        Time since the last write settles it. Silent for longer than a step, but not long:
        stalled, and worth acting on. Silent for an hour: whatever wrote it is gone.
        """
        if not meta.get("has_fragments"):
            return "finished"
        age = self.age_seconds(meta["session_id"])
        if age is not None and age >= ABANDONED_SECONDS:
            return "abandoned"
        return "running"

    def _settle_state(self, meta: dict[str, Any]) -> None:
        """Replace the feed's optimistic ``live`` with the settled state."""
        state = self.state_of(meta)
        meta["state"] = state
        meta["live"] = state == "running"
        meta["age_seconds"] = self.age_seconds(meta["session_id"])

    def is_live(self, session_id: str) -> bool:
        """Whether something is still writing to this session.

        Asked before deleting a session, so it errs towards "live": a session it cannot read
        is reported as live, because refusing to delete something is recoverable and deleting
        a running recording's directory is not.
        """
        try:
            meta = self.feed(session_id).meta()
        except Exception:
            logger.warning("Cannot read %s to check liveness; treating as live", session_id)
            return True
        return self.state_of(meta) == "running"

    def health(self, feed: SessionFeed, meta: dict[str, Any]) -> Health:
        return Health(
            meta=meta,
            steps=feed.steps(),
            actions=feed.actions(),
            age_seconds=self.age_seconds(meta["session_id"]),
        )

    def age_seconds(self, session_id: str) -> int | None:
        """Seconds since this session last wrote anything, or None if unknown."""
        import time

        newest = _activity(self._root / session_id)
        if not newest:
            return None
        return int(time.time() - newest)


def _started_at(session_dir: Path) -> tuple[float, str]:
    """When a session began, from the timestamp its id carries.

    The index used to sort by newest data file, which answers "most recently active" and is
    a different question. Touching an old session's files, or a long run still writing while
    a newer one sits idle, put the wrong row on top. A reader looking for the run they just
    started wants it first, and the id already says when it started.

    Ids look like ses_20260813_180523_b29b4b54. Anything that does not parse sorts LAST, not
    by file activity: a directory whose start time is unknown must not be able to claim it is
    the newest. Falling back to activity was tried and did exactly that, because a directory
    created just now carries a modification time later than any real session's start.
    """
    # Two shapes, because both are on disk. Current ids are 20260815-073255-dandy-willow,
    # date first. The eight runs published as reference rows predate that and are
    # ses_20260815_073254_060e426f, so reading only the new one would sort every published
    # run last, which is the failure this function exists to avoid.
    name = session_dir.name
    for stamp in (name.split("-")[:2], name.split("_")[1:3]):
        if len(stamp) != 2:
            continue
        try:
            started = datetime.strptime(f"{stamp[0]}{stamp[1]}", "%Y%m%d%H%M%S")
        except ValueError:
            continue
        return (started.timestamp(), name)
    return (0.0, name)


def _activity(session_dir: Path) -> float:
    """The newest modification time among a session's data files.

    Both layouts are checked, because the answer has to keep working across the moment a
    run ends: while it runs the fragments are newest, and once it finishes the merged
    files are.
    """
    times: list[float] = []
    fragments = session_dir / "_fragments"
    if fragments.is_dir():
        times.extend(path.stat().st_mtime for path in fragments.glob("*.parquet"))
    for name in _TRACKED:
        merged = session_dir / f"{name}.parquet"
        if merged.exists():
            times.append(merged.stat().st_mtime)
    if not times:
        # Nothing written yet. The directory's own time is the only signal, and it is
        # better than claiming the session is infinitely stale.
        return session_dir.stat().st_mtime if session_dir.exists() else 0.0
    return max(times)
