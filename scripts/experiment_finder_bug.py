"""Diagnose why find_bus_stop_spots / find_depot_spots return zero results.

Hypothesis: CmdFindBusStopSpots and CmdFindDepotSpots never call
GSRoad.SetCurrentRoadType(), so the GSTestMode dry-run of
GSRoad.BuildRoadStation() runs with no current road type selected and rejects
every candidate tile. The build commands themselves (CmdBuildRoadStop at
main.nut:1693, CmdBuildRoadDepot at :1678) DO set it, which is why building
works while finding does not.

Method: isolate each precondition the finder checks, on a tile we already know
is buildable and road-adjacent (derived from scan_town_area). If IsBuildable
and _GetAdjacentRoads both pass but the dry-run fails, and the same dry-run
succeeds once a road type is selected, the hypothesis is confirmed.

Usage:
    uv run python -m scripts.experiment_finder_bug
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


async def _scan(server: Server, town_id: int) -> dict[str, Any] | None:
    r = await server.client.send_gamescript(
        "scan_town_area", {"town_id": town_id, "radius": 8}, timeout=30.0
    )
    return r.get("result") if isinstance(r.get("result"), dict) else None


async def run(game_port: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    server = await _spawn("finder_bug", {"construction.command_pause_level": "3"}, game_port)
    try:
        c = server.client
        await c.send_rcon("unpause")
        await asyncio.sleep(2.0)

        # What road types does this game even have?
        rt = await c.send_gamescript("get_road_types", timeout=15.0)
        out["road_types"] = rt.get("result")

        towns = [t for t in ((await c.send_gamescript("get_towns", timeout=25.0)).get("result") or [])
                 if isinstance(t, dict)]
        out["town_count"] = len(towns)

        # Find a tile that is buildable AND road-adjacent, per raw classification.
        target = None
        for town in towns[:10]:
            res = await _scan(server, town.get("id"))
            if not res:
                continue
            buildable = {(t["x"], t["y"]) for t in res.get("buildable", []) if "x" in t}
            roads = {(t["x"], t["y"]) for t in res.get("roads", []) if "x" in t}
            for (bx, by) in sorted(buildable):
                for idx, (dx, dy) in enumerate(_DELTAS):
                    if (bx + dx, by + dy) in roads:
                        target = {
                            "x": bx, "y": by, "direction": idx,
                            "town_id": town.get("id"), "town_name": town.get("name"),
                            "road_at": [bx + dx, by + dy],
                        }
                        break
                if target:
                    break
            if target:
                break

        out["target"] = target
        if target is None:
            out["error"] = "no road-adjacent buildable tile"
            return out

        tid = target["town_id"]

        # 1. What does the finder itself report for this town?
        for cmd in ("find_bus_stop_spots", "find_depot_spots"):
            r = await c.send_gamescript(
                cmd, {"company_id": 0, "town_id": tid, "max_results": 5}, timeout=30.0
            )
            res = r.get("result")
            out[cmd] = {
                "success": r.get("success"),
                "error": r.get("error"),
                "count": len(res) if isinstance(res, list) else None,
            }

        # 2. Does the engine agree the tile is buildable and next to road?
        ti = await c.send_gamescript(
            "get_tile_info", {"x": target["x"], "y": target["y"]}, timeout=15.0
        )
        out["tile_info_target"] = ti.get("result")
        rx, ry = target["road_at"]
        ti2 = await c.send_gamescript("get_tile_info", {"x": rx, "y": ry}, timeout=15.0)
        out["tile_info_adjacent_road"] = ti2.get("result")

        # 3. THE TEST: the same dry-run the finder performs, via estimate_cost.
        #    estimate_cost dispatches build_road_stop, which DOES set the road
        #    type -- so if this succeeds while the finder returns nothing, the
        #    missing SetCurrentRoadType in the finder is the difference.
        params = {
            "company_id": 0,
            "x": target["x"], "y": target["y"], "direction": target["direction"],
        }
        est = await c.send_gamescript(
            "estimate_cost", {"action": "build_road_stop", "params": params}, timeout=25.0
        )
        out["dry_run_via_build_path_sets_roadtype"] = {
            "success": est.get("success"),
            "error": est.get("error"),
            "result": est.get("result"),
        }

        # 4. And the real build, to prove the tile is genuinely usable.
        build = await c.send_gamescript("build_road_stop", params, timeout=25.0)
        out["real_build"] = {
            "success": build.get("success"),
            "error": build.get("error"),
            "result": build.get("result"),
        }

        # 5. After a successful build there is now definitely road+station here;
        #    re-run the finder to see whether it stays blind.
        r = await c.send_gamescript(
            "find_bus_stop_spots", {"company_id": 0, "town_id": tid, "max_results": 5}, timeout=30.0
        )
        res = r.get("result")
        out["find_bus_stop_spots_after_build"] = {
            "count": len(res) if isinstance(res, list) else None,
        }

        # 6. Control: find_flat_spots takes a tile, not a town, and is a
        #    different code path. Does it work?
        ff = await c.send_gamescript(
            "find_flat_spots",
            {"x": target["x"], "y": target["y"], "radius": 6, "max_results": 5},
            timeout=30.0,
        )
        ffres = ff.get("result")
        out["find_flat_spots"] = {
            "success": ff.get("success"),
            "error": ff.get("error"),
            "count": len(ffres) if isinstance(ffres, list) else None,
        }
    finally:
        await _teardown(server)
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    try:
        results = {"finder_bug": await run(4970)}
    except Exception as exc:
        logger.exception("failed")
        results = {"finder_bug": {"fatal_error": repr(exc)}}
    (SCRATCH / "results_finder.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
