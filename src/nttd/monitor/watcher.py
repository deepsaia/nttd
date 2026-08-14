"""What has changed on disk, so the page can update when it happens rather than on a timer.

The page used to carry a meta refresh. Polling every few seconds is wrong in both directions at
once: it redraws when nothing has happened, and it waits up to a full interval when something
has. A step takes about a minute, so most reloads showed an identical page, and a build that
failed was visible only after the next tick.

Two fingerprints, because two different things change and they want different responses:

  DATA   a session wrote a snapshot. The browser reloads and sees it.
  CODE   a monitor source file was edited. The rendered HTML comes from those modules, so the
         SERVER has to pick them up before a reload shows anything different.

Directory mtimes rather than file contents. A recorder adds fragment files, which bumps the
directory, and hashing a run's parquet on every check would cost more than the page it saves.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# The package whose edits should restart the server. Only the monitor: a change under
# analysis/ or store/ is picked up on the next read anyway, because those are called fresh.
_SOURCE_DIR = Path(__file__).resolve().parent


class Watcher:
    """Fingerprints the session data and the monitor's own source."""

    def __init__(self, sessions_dir: Path) -> None:
        self._sessions = Path(sessions_dir)

    def data_revision(self) -> str:
        """A token that changes whenever any session writes.

        Built from directory mtimes and the fragment count, so it moves when a recorder adds a
        file and also when a session is deleted. Cheap enough to call twice a second: it is one
        scandir per session, not a parse of anything.
        """
        marks: list[str] = []
        try:
            with os.scandir(self._sessions) as entries:
                for entry in entries:
                    if not entry.is_dir():
                        continue
                    marks.append(f"{entry.name}:{entry.stat().st_mtime_ns}")
                    fragments = Path(entry.path) / "_fragments"
                    if fragments.is_dir():
                        marks.append(f"{entry.name}/f:{fragments.stat().st_mtime_ns}")
        except OSError:
            # The sessions directory may not exist yet, which is not an error: the page says
            # so, and the watcher simply reports a stable revision until it appears.
            return "none"
        marks.sort()
        return "|".join(marks) or "empty"

    def code_revision(self) -> str:
        """A token that changes whenever a monitor source file is edited."""
        marks = sorted(
            f"{path.name}:{path.stat().st_mtime_ns}"
            for path in _SOURCE_DIR.glob("*.py")
        )
        return "|".join(marks)
