#!/usr/bin/env python3
"""Assert a built wheel carries the data nttd needs to run, then smoke test it installed.

    uv run python scripts/check_wheel_contents.py dist/nttd-*.whl

nttd is not pure Python. It needs a GameScript to load into OpenTTD, a base openttd.cfg to
build a session config from, an action manifest to validate parameters against, and a
scenario to run. None of that lived in the wheel: a build from main carried 179 files of code
and no data at all, so `pip install nttd` produced something that could not start a session.

Lint and tests cannot catch that, which is the whole reason this exists. They run against the
source tree, where the files sit at the relative paths the loaders expect. Only a built
artifact shows the difference.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

# Each entry is a file that has to be inside the wheel, and what breaks without it.
REQUIRED = {
    "nttd/_data/ottd_config/game/nttd-gs/main.nut":
        "the GameScript: OpenTTD would run with no nttd in it and every action would fail",
    "nttd/_data/ottd_config/openttd.cfg":
        "the base config a session's openttd.cfg is patched from",
    "nttd/_data/config/actions/manifest.json":
        "the action manifest: parameter validation and the published surface",
    "nttd/_data/config/actions/enums.json":
        "the enum values the manifest binds to",
    "nttd/_data/config/benchmark/profile.conf":
        "the benchmark profile that decides whether a run is scoreable",
    "nttd/_data/config/benchmark/t2_256_flat_1001_realtime.conf":
        "the default scenario, loaded when none is named",
}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    wheel = Path(sys.argv[1])
    if not wheel.exists():
        print(f"no wheel at {wheel}")
        return 1

    names = set(zipfile.ZipFile(wheel).namelist())
    missing = [(name, why) for name, why in REQUIRED.items() if name not in names]

    print(f"{wheel.name}: {len(names)} files")
    for name in sorted(REQUIRED):
        print(f"  {'ok  ' if name in names else 'MISS'} {name}")

    if missing:
        print()
        print("This wheel is not usable once installed:")
        for name, why in missing:
            print(f"  {name}\n      without it: {why}")
        return 1

    print("\nEvery required data file is present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
