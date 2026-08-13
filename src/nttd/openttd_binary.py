"""The single authority on which OpenTTD executable nttd runs.

The default was the literal string "/Applications/OpenTTD.app/Contents/MacOS/openttd", written
out in six places: the server, the verify command, two scripts, a shell script and a test. On
any machine that is not a Mac with OpenTTD installed from the app bundle, nothing started
unless NTTD_OPENTTD_BINARY was set, and the failure was a bare "No such file or directory"
naming a path the user had never heard of. nttd was macOS-only in practice while claiming not
to be.

Resolved here instead, for the same reason as `resources`: this was decided in several places
and they could not disagree usefully. PATH first, because that is where a package manager puts
it and where a container has it, then the app bundle, because that is how OpenTTD is normally
installed on macOS and it adds nothing to PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ENV_VAR = "NTTD_OPENTTD_BINARY"

# Names to look for on PATH. Debian and Ubuntu package the graphics-free build as
# openttd-dedicated; nttd always launches with -D, so either one serves.
_NAMES_ON_PATH = ("openttd", "openttd-dedicated")

# Installations that put nothing on PATH. The macOS app bundle is the case that matters: it
# is the normal way to install OpenTTD there, and it is what every hardcoded path meant.
_BUNDLE_PATHS = (
    Path("/Applications/OpenTTD.app/Contents/MacOS/openttd"),
    Path.home() / "Applications" / "OpenTTD.app" / "Contents" / "MacOS" / "openttd",
)


def find_openttd() -> str | None:
    """Return the OpenTTD executable to run, or None if the search found nothing.

    The environment variable wins outright and is returned unchecked, so an operator pointing
    at a build that does not exist yet is told which path failed rather than being silently
    given a different binary than the one they named.
    """
    configured = os.environ.get(ENV_VAR)
    if configured:
        return configured

    for name in _NAMES_ON_PATH:
        found = shutil.which(name)
        if found:
            return found

    for path in _BUNDLE_PATHS:
        if path.exists():
            return str(path)

    return None


def openttd_binary() -> str:
    """Return the executable to run, falling back to a bare name when none was found.

    Deliberately does not raise. This is read at import by the API server, and a machine
    without OpenTTD must still be able to import nttd, run its tests, and read a recorded
    session. Falling back to "openttd" means the failure arrives at spawn, where it belongs,
    and names something the user can act on rather than a path they never chose.
    """
    return find_openttd() or _NAMES_ON_PATH[0]


def search_description() -> str:
    """Where the search looked, for an error or startup message worth reading."""
    return (
        f"set {ENV_VAR}, or install OpenTTD so that one of "
        f"{', '.join(_NAMES_ON_PATH)} is on PATH"
    )
