"""Probe helper for the pause/time experiments.

Spawns one scratch server, then reports what towns/tiles exist and whether a
construction command succeeds while paused. Used to find a build target that
Experiment 1 can rely on.

Usage:
    uv run python scripts/experiment_probe.py [--timekeeping N] [--minutes N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.experiment_pause_and_time import _spawn, _teardown  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger("experiment").setLevel(logging.INFO)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timekeeping", type=int, default=0)
    parser.add_argument("--minutes", type=int, default=12)
    parser.add_argument("--port", type=int, default=4700)
    args = parser.parse_args()

    out: dict[str, Any] = {}
    server = await _spawn(
        "probe",
        {
            "economy.timekeeping_units": str(args.timekeeping),
            "economy.minutes_per_calendar_year": str(args.minutes),
        },
        args.port,
    )
    try:
        c = server.client
        for key in ("economy.timekeeping_units", "economy.minutes_per_calendar_year"):
            lines = await c.send_rcon(f"setting {key}")
            out[key] = " | ".join(x.strip() for x in lines if x.strip())

        towns = await c.send_gamescript("get_towns", timeout=25.0)
        tlist = towns.get("result") or []
        out["town_count"] = len(tlist) if isinstance(tlist, list) else None
        out["towns_sample"] = tlist[:4] if isinstance(tlist, list) else tlist

        if isinstance(tlist, list) and tlist:
            tid = tlist[0].get("id")
            out["probe_town_id"] = tid
            for cmd, params in (
                ("find_bus_stop_spots", {"company_id": 0, "town_id": tid, "max_results": 5}),
                ("find_depot_spots", {"company_id": 0, "town_id": tid, "max_results": 5}),
                ("scan_town_area", {"town_id": tid, "radius": 6}),
            ):
                r = await c.send_gamescript(cmd, params, timeout=30.0)
                res = r.get("result")
                out[cmd] = {
                    "success": r.get("success"),
                    "error": r.get("error"),
                    "count": len(res) if isinstance(res, list) else None,
                    "sample": res[:3] if isinstance(res, list) else res,
                }
    finally:
        await _teardown(server)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
