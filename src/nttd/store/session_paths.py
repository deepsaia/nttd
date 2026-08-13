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
import string
from collections.abc import Iterator
from pathlib import Path

ENV_VAR = "NTTD_SESSIONS_DIR"
DEFAULT_SESSIONS_DIR = Path("logs/sessions")

# What a session id may contain. Every id nttd mints is "ses_<date>_<time>_<8 hex>", and the
# tests use short forms like "ses_001", so letters, digits, dot, dash and underscore admit all
# of them. Checked as a character set rather than a pattern, because the interesting property
# is not "looks like an id" but "cannot be anything other than one directory name".
_ALLOWED_CHARACTERS = frozenset(string.ascii_letters + string.digits + "._-")

# Longer than any id nttd mints, at 28 characters, and short of the 255 a filesystem takes.
_MAX_LENGTH = 128


class InvalidSessionIdError(ValueError):
    """A session id that could name something other than one directory under the root."""


def validate_session_id(session_id: str) -> str:
    """Return the id unchanged, or raise if it could escape the sessions root.

    Every path here is built by joining a caller's string onto the root, and 34 HTTP routes
    take one as a path parameter. `Path("logs/sessions") / "../../etc"` is a path to /etc, and
    the session directory is read, written, and in one case removed whole.

    Excluding the separators is what makes this safe: with no "/" or "\\" the result is a
    single path component, so it cannot climb out whatever else it contains. That is why "a..b"
    passes while ".." does not, and why an absolute path fails on its leading separator.

    Deliberately not implemented by resolving the path and testing that the root contains it.
    Both the root and the temporary directories the tests use can sit behind symlinks, macOS
    resolves /tmp to /private/tmp, and a containment test across a symlink rejects paths that
    were never a problem. Rejecting the characters needs no filesystem at all.
    """
    if not session_id:
        raise InvalidSessionIdError("session id is empty")
    if len(session_id) > _MAX_LENGTH:
        raise InvalidSessionIdError(
            f"session id is longer than {_MAX_LENGTH} characters: {len(session_id)}",
        )
    if session_id in {".", ".."}:
        raise InvalidSessionIdError(f"session id names a directory, not a session: {session_id!r}")

    offending = sorted(set(session_id) - _ALLOWED_CHARACTERS)
    if offending:
        raise InvalidSessionIdError(
            f"session id contains characters that are not allowed: {''.join(offending)!r}",
        )
    return session_id


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
    """Return the directory holding one session's data.

    Validated here rather than at each caller for the same reason the root is resolved here:
    there are 23 modules on this path and they would not agree. This is the one join of an
    untrusted string onto the root, so it is the one place the check cannot be forgotten.
    """
    return sessions_dir() / validate_session_id(session_id)


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
