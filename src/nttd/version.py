"""nttd's version, read from installed metadata rather than written down.

There is one source of truth and it is the git tag the GitHub release created: hatch-vcs
derives the distribution version from it at build time, and this reads it back at run time.

It used to be written in pyproject as well, which is one fact in two places, and a release is
exactly when they diverge: pyproject said 0.1.0 while the 0.0.2 release was cut, so publish
refused at its own version gate and uploaded nothing. The gate was right; the duplication was
the bug.

Not in ``__init__.py``, which stays empty by project convention.
"""

from __future__ import annotations

from importlib import metadata

# A checkout that was never installed has no metadata to read. Reported as such rather than
# guessed at: a wrong version in a recorded result is worse than an honest unknown.
UNKNOWN = "unknown"


def version() -> str:
    """The installed version of nttd, or ``unknown`` when it is not installed."""
    try:
        return metadata.version("nttd")
    except metadata.PackageNotFoundError:
        return UNKNOWN
