"""The single authority on where session data lives on disk.

Every module that needs a session directory resolves it here. It used to be
resolved in eight places: api/app.py, analysis/loader.py, three CLI modules, and a
private global in each of the repositories. They disagreed. Only session_repo was
ever handed the configured directory, so with NTTD_SESSIONS_DIR set the action,
event, entity and metrics repositories all read the default `logs/sessions` and
reported an empty session for a run that had recorded plenty.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

ENV_VAR = "NTTD_SESSIONS_DIR"
DEFAULT_SESSIONS_DIR = Path("logs/sessions")


def sessions_dir() -> Path:
    """Return the configured root directory for session data.

    Resolved per call rather than captured at import, so setting NTTD_SESSIONS_DIR
    after nttd is imported still takes effect. An import-time constant is what made
    this hard to get right: a test or a CLI entry point that set the variable during
    startup was ignored by whichever module had already been imported.
    """
    configured = os.environ.get(ENV_VAR)
    return Path(configured) if configured else DEFAULT_SESSIONS_DIR


def session_dir(session_id: str) -> Path:
    """Return the directory holding one session's data."""
    return sessions_dir() / session_id


def session_file(session_id: str, filename: str) -> Path:
    """Return the path to a named file inside one session's directory."""
    return session_dir(session_id) / filename


def iter_session_dirs() -> Iterator[Path]:
    """Yield every session directory, newest first.

    Yields nothing if the root does not exist, which is the normal state before the
    first session is recorded rather than an error.
    """
    root = sessions_dir()
    if not root.exists():
        return
    for path in sorted(root.iterdir(), reverse=True):
        if path.is_dir():
            yield path
