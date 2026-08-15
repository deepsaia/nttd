"""config/actions/enums.json still describes the OpenTTD on this machine.

Of the three files in config/actions, this is the one that goes stale without anyone touching
it. manifest.json is regenerated from the GameScript and CI fails when it drifts.
descriptions.json is prose, and prose does not expire. enums.json holds constant values read
out of a specific OpenTTD build, so upgrading the game invalidates it and nothing said so.

Getting one wrong is quiet and expensive. OF_UNLOAD and OF_SERVICE_IF_NEEDED are both 4, so
the game accepts either and does the wrong thing: an order flag that means "unload here" would
silently become "service if needed". That is why enum values are read from the binary rather
than written down, and why the recorded version is worth checking.

Skipped without a binary, because a version cannot be compared against a game that is not
here. That makes this useless in CI by design, and useful on the machine that upgrades OpenTTD,
which is where the mistake is actually made.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from nttd import resources

_ENUMS_PATH = resources.action_config("enums.json")
_MANIFEST_PATH = resources.action_config("manifest.json")


def _recorded() -> dict:
    return json.loads(_ENUMS_PATH.read_text())


@pytest.fixture(scope="module")
def running_version() -> str:
    """The version of the OpenTTD on this machine, from the binary itself.

    Note the exit status is ignored. OpenTTD has no --version flag: it prints its version,
    follows it with the usage text, and exits 1. So the first line of output is the only
    trustworthy signal, and treating the status as failure would skip on a healthy install.
    """
    binary = os.environ.get(
        "NTTD_OPENTTD_BINARY", "/Applications/OpenTTD.app/Contents/MacOS/openttd",
    )
    if not Path(binary).exists():
        pytest.skip("No OpenTTD binary, so its version cannot be compared")

    result = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False,
    )
    first_line = (result.stdout or result.stderr).strip().splitlines()
    if not first_line:
        pytest.skip("The OpenTTD binary printed no version")

    # "OpenTTD 15.3" -> "15.3"
    parts = first_line[0].split()
    if len(parts) < 2 or parts[0] != "OpenTTD":
        pytest.skip(f"Could not read a version from {first_line[0]!r}")
    return parts[1]


def test_the_recorded_enum_version_matches_the_installed_game(running_version: str) -> None:
    recorded = _recorded()["openttd_version"]
    assert recorded == running_version, (
        f"config/actions/enums.json was read from OpenTTD {recorded} but this machine runs "
        f"{running_version}. Constants may have moved. Re-extract them with "
        f"'uv run python scripts/dump_gs_enums.py', then regenerate the manifest."
    )


def test_the_manifest_agrees_with_the_enums_it_was_built_from() -> None:
    """Both files record the version, and the manifest copies it at generation time. If they
    disagree, one of the two was regenerated without the other and the published surface
    describes constants from a build nobody has.
    """
    assert json.loads(_MANIFEST_PATH.read_text())["enum_values_from"] == (
        _recorded()["openttd_version"]
    )


def test_the_enums_file_says_where_it_came_from() -> None:
    """The provenance the README promises is machine-readable, not only prose, so a reader who
    opens the file rather than the directory still learns not to hand-edit it.
    """
    recorded = _recorded()
    assert "dump_gs_enums" in recorded["source"]
    assert recorded["enums"], "no enums recorded at all"
