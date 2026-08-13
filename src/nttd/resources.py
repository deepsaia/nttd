"""The single authority on where nttd's bundled data lives.

nttd is not pure Python. It needs a GameScript to load into OpenTTD, a base ``openttd.cfg``
to build a session config from, an action manifest to validate parameters against, and
scenario files to run. All of that sits outside ``src/`` in the repository, and five modules
found it by counting ``..`` from their own ``__file__`` up to the repository root.

That works from a checkout and only from a checkout. Measured on a wheel built from main:
179 files, and no ``main.nut``, ``manifest.json``, ``openttd.cfg`` or scenario config among
them. Installing it and asking for the manifest looked for
``site-packages/../../config/actions/manifest.json``, because ``parents[3]`` from
``nttd/config/`` climbs out of site-packages entirely. So ``pip install nttd`` produced
something that could not run a session, and nothing noticed because every test runs from the
checkout where the counting happens to work.

Resolved here, once, for both cases: the packaged copy when nttd is installed, the repository
when it is not. One module rather than five call sites, for the same reason
``store/session_paths`` exists: this used to be resolved in several places and they disagreed.
"""

from __future__ import annotations

import os
from pathlib import Path

# Where the wheel puts the data, relative to the nttd package. See the force-include rules in
# pyproject.toml, which map the repository's ottd_config/ and config/ into here.
_PACKAGED = Path(__file__).resolve().parent / "_data"

# Where it lives in a checkout: the repository root, three levels above src/nttd.
_CHECKOUT = Path(__file__).resolve().parents[2]

# Overrides the lot, for an operator running against their own game files.
ENV_VAR = "NTTD_DATA_DIR"


def data_dir() -> Path:
    """The directory holding nttd's bundled data.

    Packaged copy first, so an installed nttd never depends on the working directory or on a
    repository existing. A checkout falls through to the repository root, which is what every
    test and every development run uses.
    """
    configured = os.environ.get(ENV_VAR)
    if configured:
        return Path(configured)
    if _PACKAGED.is_dir():
        return _PACKAGED
    return _CHECKOUT


def gamescript_dir() -> Path:
    """The OpenTTD config template directory, holding the GameScript, AI and openttd.cfg.

    Named for the GameScript because that is the part that matters: without it OpenTTD runs
    with no nttd in it, and every action returns nothing.
    """
    return data_dir() / "ottd_config"


def action_config(filename: str) -> Path:
    """One of the generated action files: manifest.json, descriptions.json, enums.json."""
    return data_dir() / "config" / "actions" / filename


def scenario_config(filename: str) -> Path:
    """One of the shipped scenario or profile files under config/benchmark."""
    return data_dir() / "config" / "benchmark" / filename
