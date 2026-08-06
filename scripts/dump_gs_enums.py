#!/usr/bin/env python3
"""Read the GameScript API's enum values out of the OpenTTD build itself.

    uv run python scripts/dump_gs_enums.py

Many nttd actions take a bare integer and hand it straight to the GameScript API:
``set_order_condition`` passes ``condition`` to ``GSOrder.SetOrderCondition``,
``remove_rail_track`` passes ``track`` to ``GSRail.RemoveRailTrack``, and so on. An agent
given only the parameter name cannot call any of them, because the accepted values are
OpenTTD constants that appear nowhere in nttd.

Writing those tables by hand is the obvious approach and the wrong one. They are long,
they are version-specific, and a wrong integer is worse than a missing one: it is a
plausible value the game will accept and act on. ``OF_FULL_LOAD`` and ``OF_NO_LOAD`` are
one bit apart.

So they are read from the same OpenTTD binary a session runs on. This launches a
throwaway server with a probe GameScript that iterates the API classes and reports every
integer constant it finds. The values are therefore ground truth for that build, and
regenerating on a new OpenTTD reports what changed rather than silently disagreeing.

The output, ``config/actions/enums.json``, is merged into the manifest by
``generate_action_manifest.py``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT = ROOT / "config" / "actions" / "enums.json"
BASE_CONFIG = ROOT / "ottd_config"

DEFAULT_BINARY = "/Applications/OpenTTD.app/Contents/MacOS/openttd"

# Every API class an nttd action passes a constant to. Iterated wholesale rather than
# named member by member, so a constant added upstream is picked up without an edit here.
PROBED_CLASSES = [
    "GSAirport",
    "GSBridge",
    "GSCargo",
    "GSCompany",
    "GSEngine",
    "GSGroup",
    "GSIndustryType",
    "GSOrder",
    "GSRail",
    "GSRoad",
    "GSStation",
    "GSSubsidy",
    "GSTile",
    "GSTown",
    "GSVehicle",
]

_MARKER = "NTTDENUM"
_LINE = re.compile(rf"{_MARKER} (\w+)\.(\w+)=(-?\d+)")


def _probe_source() -> str:
    """A GameScript that reports every integer constant on the probed classes.

    Squirrel classes are iterable, so this enumerates members rather than being handed a
    list of names to look up. A hand-listed set of names is the same defect as a
    hand-listed set of values: it goes stale silently.
    """
    # Each class is named literally rather than looked up in the root table: the API
    # classes are not registered there, so a lookup returns null and the iteration dies
    # partway through with a Squirrel stack trace instead of a result.
    blocks = "\n".join(
        f"""    try {{
      foreach (key, value in {name}) {{
        if (typeof value == "integer") {{
          GSLog.Info("{_MARKER} {name}." + key + "=" + value);
        }}
      }}
    }} catch (e) {{ GSLog.Info("{_MARKER}SKIP {name}"); }}"""
        for name in PROBED_CLASSES
    )
    return f"""
class NttdEnumProbe extends GSController {{
  function Start() {{
{blocks}
    GSLog.Info("{_MARKER} COMPLETE");
  }}
}}
"""


def _probe_info() -> str:
    """Registration for the probe, replacing nttd's own so the config still resolves."""
    return """
class NttdGSInfo extends GSInfo {
    function GetAuthor()      { return "nttd"; }
    function GetName()        { return "nttd GameScript"; }
    function GetShortName()   { return "NTTD"; }
    function GetDescription() { return "Enum probe."; }
    function GetVersion()     { return 1; }
    function GetDate()        { return "2026-03-10"; }
    function GetAPIVersion()  { return "15"; }
    function CreateInstance() { return "NttdEnumProbe"; }
    function GetURL()         { return ""; }
    function MinVersionToLoad() { return 1; }
}

RegisterGS(NttdGSInfo());
"""


def _run_probe(binary: str, work_dir: Path) -> str:
    """Start a throwaway server with the probe installed and return what it logged.

    The probe replaces main.nut in a copy of the real config directory. OpenTTD resolves
    a GameScript by the name in ``[game_scripts]``, so keeping the name and swapping the
    body is what makes it load without touching the config.
    """
    config_dir = work_dir / "config"
    shutil.copytree(BASE_CONFIG, config_dir)
    gs_dir = config_dir / "game" / "nttd-gs"
    (gs_dir / "main.nut").write_text(_probe_source())
    (gs_dir / "info.nut").write_text(_probe_info())

    # -d script=9 is not optional. GSLog.Info writes to the script debug channel, not to
    # stdout, so without it the probe runs, reports everything, and appears to have
    # printed nothing at all.
    process = subprocess.Popen(
        [binary, "-D", "-c", str(config_dir / "openttd.cfg"), "-d", "script=9"],
        cwd=config_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output: list[str] = []
    try:
        for line in process.stdout or []:
            output.append(line)
            if f"{_MARKER} COMPLETE" in line:
                break
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return "".join(output)


def parse(output: str) -> dict[str, dict[str, int]]:
    """Group the reported constants by API class."""
    enums: dict[str, dict[str, int]] = {}
    for klass, member, value in _LINE.findall(output):
        enums.setdefault(klass, {})[member] = int(value)
    return {name: dict(sorted(members.items())) for name, members in sorted(enums.items())}


def _openttd_version(binary: str) -> str:
    """Record which build the values came from, so a change of build is visible."""
    result = subprocess.run(
        [binary, "--help"], capture_output=True, text=True, timeout=10, check=False
    )
    match = re.search(r"OpenTTD\s+([\w.\-]+)", result.stdout + result.stderr)
    return match.group(1) if match else "unknown"


def main() -> None:
    binary = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BINARY
    if not Path(binary).exists():
        print(f"No OpenTTD binary at {binary}", file=sys.stderr)
        print("Pass one: uv run python scripts/dump_gs_enums.py /path/to/openttd", file=sys.stderr)
        raise SystemExit(1)

    with tempfile.TemporaryDirectory(prefix="nttd-enum-probe-") as temp:
        output = _run_probe(binary, Path(temp))

    enums = parse(output)
    if not enums:
        print("The probe reported nothing. Output follows:", file=sys.stderr)
        print(output[-3000:], file=sys.stderr)
        raise SystemExit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "openttd_version": _openttd_version(binary),
                "source": "read from the OpenTTD build by scripts/dump_gs_enums.py",
                "enums": enums,
            },
            indent=2,
        )
        + "\n"
    )

    total = sum(len(members) for members in enums.values())
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    print(f"  classes   : {len(enums)}")
    print(f"  constants : {total}")


if __name__ == "__main__":
    main()
