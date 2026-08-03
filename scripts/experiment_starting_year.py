"""Check what a starting_year of 2020 actually does to a benchmark world.

The bundled scenarios moved from 1960 to 2020. That is a bigger change than it
looks, because the calendar year decides which vehicles exist: OpenTTD introduces
and retires engines by date, so a 2020 start is not "1960 with a different label".
Two things need confirming before benchmarks rely on it:

  1. OpenTTD accepts the year and reports it back, rather than clamping it.
  2. The available-vehicle set at 2020 is non-empty for every transport mode, so a
     scenario cannot silently become unplayable for road, rail, air, or water.

Also samples 1960 for comparison, since a tier is only comparable if every
contestant in it faces the same engines.

Usage:
    uv run python -m scripts.experiment_starting_year
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nttd.bridge.admin_client import AdminClient  # noqa: E402
from nttd.runtime.config_builder import build_session_config  # noqa: E402
from nttd.utils.game_date import game_date_to_year  # noqa: E402
from scripts.experiment_pause_and_time import (  # noqa: E402
    _SMALL_MAP_SETTINGS,
    ADMIN_PASSWORD,
    BASE_CONFIG,
    OPENTTD_BINARY,
    SCRATCH,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)

# The GS names, not the OpenTTD enum names: _VehicleTypeEnum accepts
# train/road/ship/aircraft and silently falls back to rail for anything else, so
# a wrong name here would report rail counts four times.
_VEHICLE_TYPES = ("train", "road", "ship", "aircraft")


async def _probe_year(name: str, game_port: int, year: int) -> dict[str, Any]:
    """Start a server at the given year and report the date and engine counts."""
    session_dir = SCRATCH / name
    if session_dir.exists():
        shutil.rmtree(session_dir)
    admin_port = game_port + 1

    settings = dict(_SMALL_MAP_SETTINGS)
    settings["game_creation.starting_year"] = str(year)
    build_session_config(
        base_config_dir=BASE_CONFIG,
        session_dir=session_dir,
        game_port=game_port,
        admin_port=admin_port,
        admin_password=ADMIN_PASSWORD,
        settings=settings,
    )

    proc = await asyncio.create_subprocess_exec(
        OPENTTD_BINARY, "-D", "-c", str(session_dir / "openttd.cfg"), "-G", "4242",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    client = AdminClient(host="127.0.0.1", port=admin_port)
    poll: asyncio.Task[Any] | None = None
    try:
        deadline = time.time() + 40.0
        while time.time() < deadline:
            if await client.connect(password=ADMIN_PASSWORD, name=f"year_{year}"):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError(f"[{name}] admin port never came up")

        poll = asyncio.create_task(client.poll_loop(), name=f"poll_{name}")
        await client.subscribe_defaults()
        for _ in range(40):
            if (await client.send_gamescript("ping", timeout=5.0)).get("success"):
                break
            await asyncio.sleep(0.5)

        date = await client.send_gamescript("get_date", {})
        game_date = (date.get("result") or {}).get("date", 0)

        engines: dict[str, int] = {}
        for vehicle_type in _VEHICLE_TYPES:
            reply = await client.send_gamescript(
                "get_engines", {"vehicle_type": vehicle_type}, timeout=20.0,
            )
            listed = reply.get("result")
            engines[vehicle_type] = len(listed) if isinstance(listed, list) else -1

        return {
            "requested_year": year,
            "game_date": game_date,
            "reported_year": game_date_to_year(game_date) if game_date else None,
            "engines": engines,
        }
    finally:
        if poll is not None:
            poll.cancel()
        await client.disconnect()
        proc.terminate()
        await proc.wait()


async def main() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    findings = []
    for offset, year in enumerate((1960, 2020)):
        finding = await _probe_year(f"year_{year}", 3999 + offset * 10, year)
        logger.info(
            "year=%s -> reported=%s engines=%s",
            finding["requested_year"], finding["reported_year"], finding["engines"],
        )
        findings.append(finding)

    print("\n=== starting_year probe ===")
    for finding in findings:
        accepted = finding["reported_year"] == finding["requested_year"]
        print(
            f"  requested {finding['requested_year']} -> reported "
            f"{finding['reported_year']}  accepted={accepted}"
        )
        for vehicle_type, count in finding["engines"].items():
            print(f"      {vehicle_type:6s} engines: {count}")


if __name__ == "__main__":
    asyncio.run(main())
