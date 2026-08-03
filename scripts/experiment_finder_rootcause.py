"""Isolate the finder bug: stale road type vs. an existing station.

find_bus_stop_spots returns 0 results on a fresh session but 5 after a
build_road_stop succeeds. Two candidate explanations:

  (a) GSRoad.SetCurrentRoadType() is never called by the finder, so its
      GSTestMode dry-run of BuildRoadStation runs with no current road type
      and rejects every tile. CmdBuildRoadStop DOES set it (main.nut:1693),
      and the setting is script-global, so any prior build "fixes" the finder.

  (b) The finder needs an existing station nearby for some other reason.

The discriminator: estimate_cost dispatches build_road_stop under GSTestMode,
so it sets the current road type but builds NOTHING. If the finder starts
working after estimate_cost alone, (a) is proven and (b) is refuted.

Usage:
    uv run python -m scripts.experiment_finder_rootcause
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.experiment_pause_and_time import SCRATCH, Server, _spawn, _teardown  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)

_DELTAS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


async def _find_target(server: Server) -> dict[str, Any] | None:
    """Locate a buildable, road-adjacent tile via raw tile classification."""
    towns = [t for t in ((await server.client.send_gamescript("get_towns", timeout=25.0)).get("result") or [])
             if isinstance(t, dict)]
    for town in towns[:10]:
        r = await server.client.send_gamescript(
            "scan_town_area", {"town_id": town.get("id"), "radius": 8}, timeout=30.0
        )
        res = r.get("result")
        if not isinstance(res, dict):
            continue
        buildable = {(t["x"], t["y"]) for t in res.get("buildable", []) if "x" in t}
        roads = {(t["x"], t["y"]) for t in res.get("roads", []) if "x" in t}
        for (bx, by) in sorted(buildable):
            for idx, (dx, dy) in enumerate(_DELTAS):
                if (bx + dx, by + dy) in roads:
                    return {"x": bx, "y": by, "direction": idx, "town_id": town.get("id")}
    return None


async def _finder_counts(server: Server, town_id: int) -> dict[str, Any]:
    """Report how many spots each town-scoped road finder returns."""
    counts = {}
    for cmd in ("find_bus_stop_spots", "find_depot_spots"):
        r = await server.client.send_gamescript(
            cmd, {"company_id": 0, "town_id": town_id, "max_results": 5}, timeout=30.0
        )
        res = r.get("result")
        counts[cmd] = len(res) if isinstance(res, list) else None
    return counts


async def run(game_port: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    server = await _spawn("rootcause", {"construction.command_pause_level": "3"}, game_port)
    try:
        c = server.client
        await c.send_rcon("unpause")
        await asyncio.sleep(2.0)

        target = await _find_target(server)
        out["target"] = target
        if target is None:
            out["error"] = "no target"
            return out
        tid = target["town_id"]
        params = {
            "company_id": 0,
            "x": target["x"], "y": target["y"], "direction": target["direction"],
        }

        # STEP 1: fresh session, no road type ever set.
        out["step1_fresh_session"] = await _finder_counts(server, tid)

        # STEP 2: estimate_cost -- sets current road type via CmdBuildRoadStop,
        #         but under GSTestMode so nothing is actually built.
        est = await c.send_gamescript(
            "estimate_cost", {"action": "build_road_stop", "params": params}, timeout=25.0
        )
        out["step2_estimate_cost"] = {
            "success": est.get("success"), "result": est.get("result"),
        }
        stations = await c.send_gamescript("get_stations", {"company_id": 0}, timeout=15.0)
        slist = stations.get("result")
        out["step2_station_count"] = len(slist) if isinstance(slist, list) else None

        # STEP 3: re-run the finders. Nothing was built. If counts are now
        #         non-zero, the only thing that changed is the current road type.
        out["step3_after_dry_run_only"] = await _finder_counts(server, tid)

        out["verdict"] = (
            "CONFIRMED (a): finder depends on a road type set by an earlier command"
            if (out["step3_after_dry_run_only"].get("find_bus_stop_spots") or 0) > 0
            and out["step2_station_count"] == 0
            else "NOT confirmed by dry-run alone -- investigate further"
        )
    finally:
        await _teardown(server)
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    try:
        results = {"rootcause": await run(4980)}
    except Exception as exc:
        logger.exception("failed")
        results = {"rootcause": {"fatal_error": repr(exc)}}
    (SCRATCH / "results_rootcause.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
