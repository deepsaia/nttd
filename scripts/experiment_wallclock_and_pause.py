"""Follow-up experiments: wallclock timekeeping, and build-while-paused.

Experiment 2b -- economy.timekeeping_units = 1 ("wallclock") unlocks
    economy.minutes_per_calendar_year over the range 0..10080 instead of
    clamping it to 12. Measure the actual game-day rate at several values to
    find out how much simulated time a bounded session can cover.

Experiment 1b -- build while paused, using a build target derived from
    scan_town_area (which reports raw tile classification) rather than from
    the find_* helpers (which use GSTestMode dry-runs that may themselves be
    affected by pause).

Usage:
    uv run python -m scripts.experiment_wallclock_and_pause
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.experiment_pause_and_time import (  # noqa: E402
    SCRATCH,
    Server,
    _game_date,
    _read_setting,
    _spawn,
    _teardown,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)


async def _measure_day_rate(server: Server, label: str, seconds: float) -> dict[str, Any]:
    """Measure elapsed game days over a wall-clock window."""
    d0 = await _game_date(server)
    t0 = time.monotonic()
    await asyncio.sleep(seconds)
    d1 = await _game_date(server)
    wall = time.monotonic() - t0
    days = (d1.get("date") or 0) - (d0.get("date") or 0)
    rate = wall / days if days else None
    logger.info(
        "[%s] %s: %d game-days in %.1fs -> %s s/day | %s min/game-year",
        server.name, label, days, wall,
        f"{rate:.3f}" if rate else "n/a",
        f"{rate * 365 / 60:.2f}" if rate else "n/a",
    )
    return {
        "game_days": days,
        "wall_seconds": round(wall, 2),
        "seconds_per_game_day": round(rate, 4) if rate else None,
        "implied_minutes_per_game_year": round(rate * 365 / 60, 2) if rate else None,
        "game_years_per_wall_hour": round(3600 / (rate * 365), 2) if rate else None,
    }


async def experiment_wallclock_rates() -> dict[str, Any]:
    """Bake several minutes_per_calendar_year values in wallclock mode and measure."""
    out: dict[str, Any] = {}
    port = 4800
    for minutes in (12, 3, 1):
        name = f"wallclock_{minutes}min"
        server = await _spawn(
            name,
            {
                "economy.timekeeping_units": "1",
                "economy.minutes_per_calendar_year": str(minutes),
            },
            port,
        )
        port += 10
        try:
            entry: dict[str, Any] = {
                "configured_minutes_per_calendar_year": minutes,
                "setting_readback": await _read_setting(
                    server, "economy.minutes_per_calendar_year"
                ),
                "timekeeping_readback": await _read_setting(server, "economy.timekeeping_units"),
            }
            await server.client.send_rcon("unpause")
            await asyncio.sleep(2.0)
            entry["measured"] = await _measure_day_rate(server, f"baked {minutes} min/yr", 20.0)

            # Can it be retuned at runtime in wallclock mode?
            rc = await server.client.send_rcon("setting economy.minutes_per_calendar_year 2")
            entry["runtime_rcon_output"] = [x.strip() for x in rc if x.strip()]
            await asyncio.sleep(1.0)
            entry["setting_after_runtime_set"] = await _read_setting(
                server, "economy.minutes_per_calendar_year"
            )
            entry["measured_after_runtime_set"] = await _measure_day_rate(
                server, "after runtime set to 2", 15.0
            )
            out[name] = entry
        finally:
            await _teardown(server)
    return out


async def _pick_build_tile(server: Server) -> dict[str, Any] | None:
    """Find a road tile with an adjacent buildable tile, via raw tile classification.

    Returns {x, y, direction} for a bus stop: the buildable tile plus the
    direction index whose adjacent tile is the road.
    """
    towns = await server.client.send_gamescript("get_towns", timeout=25.0)
    tlist = towns.get("result") or []
    if not isinstance(tlist, list):
        return None

    # Direction convention (docs/orientation_research.md): 0=+x, 1=+y, 2=-x, 3=-y
    deltas = [(1, 0), (0, 1), (-1, 0), (0, -1)]

    for town in tlist[:12]:
        r = await server.client.send_gamescript(
            "scan_town_area", {"town_id": town.get("id"), "radius": 8}, timeout=30.0
        )
        res = r.get("result")
        if not isinstance(res, dict):
            continue
        buildable = {(t["x"], t["y"]) for t in res.get("buildable", []) if "x" in t}
        roads = {(t["x"], t["y"]) for t in res.get("roads", []) if "x" in t}
        for (bx, by) in sorted(buildable):
            for idx, (dx, dy) in enumerate(deltas):
                if (bx + dx, by + dy) in roads:
                    return {
                        "x": bx, "y": by, "direction": idx,
                        "town_id": town.get("id"), "town_name": town.get("name"),
                        "adjacent_road": [bx + dx, by + dy],
                    }
    return None


async def experiment_build_while_paused(pause_level: int, game_port: int) -> dict[str, Any]:
    """Attempt construction while paused at a given command_pause_level."""
    name = f"pause2_level_{pause_level}"
    out: dict[str, Any] = {"pause_level": pause_level}
    server = await _spawn(
        name, {"construction.command_pause_level": str(pause_level)}, game_port
    )
    try:
        out["setting_readback"] = await _read_setting(server, "construction.command_pause_level")

        # Find a target while the game is RUNNING, so discovery is never the
        # thing that pause interferes with.
        await server.client.send_rcon("unpause")
        await asyncio.sleep(2.0)
        target = await _pick_build_tile(server)
        out["target"] = target
        if target is None:
            out["error"] = "no road-adjacent buildable tile found"
            return out

        # Confirm the clock is frozen once paused.
        await server.client.send_rcon("pause")
        await asyncio.sleep(1.0)
        d0 = await _game_date(server)
        await asyncio.sleep(3.0)
        d1 = await _game_date(server)
        out["clock_frozen_when_paused"] = (d1.get("date") == d0.get("date"))

        params = {
            "company_id": 0,
            "x": target["x"],
            "y": target["y"],
            "direction": target["direction"],
        }

        # THE TEST 1: a dry-run (GSTestMode) while paused.
        est = await server.client.send_gamescript(
            "estimate_cost", {"action": "build_road_stop", "params": params}, timeout=20.0
        )
        out["dry_run_while_paused"] = {
            "success": bool(est.get("success")),
            "error": est.get("error"),
            "result": est.get("result"),
        }

        # THE TEST 2: a real construction command while paused.
        build = await server.client.send_gamescript("build_road_stop", params, timeout=25.0)
        out["build_while_paused"] = {
            "success": bool(build.get("success")),
            "error": build.get("error"),
            "result": build.get("result"),
        }

        # Contrast: a non-construction command while paused.
        loan = await server.client.send_gamescript(
            "set_loan", {"company_id": 0, "amount": 120000}, timeout=15.0
        )
        out["nonconstruction_while_paused"] = {
            "success": bool(loan.get("success")), "error": loan.get("error"),
        }

        # Control: if the paused build failed, does the identical call work once
        # running? That attributes the failure to pause rather than to the tile.
        if not build.get("success"):
            await server.client.send_rcon("unpause")
            await asyncio.sleep(2.5)
            retry = await server.client.send_gamescript("build_road_stop", params, timeout=25.0)
            out["same_build_while_running"] = {
                "success": bool(retry.get("success")),
                "error": retry.get("error"),
                "result": retry.get("result"),
            }
    finally:
        await _teardown(server)
    return out


async def experiment_queue_and_flush(game_port: int) -> dict[str, Any]:
    """Deliberate while paused, then unpause and flush a whole action batch.

    This is the fallback turn design if construction while paused is rejected:
    the step boundary is still a hard barrier for DECIDING, but the actions are
    applied in a brief unpaused window. The question this answers is whether a
    multi-action batch (build stop, build depot, buy vehicle, order, start)
    survives a flush window short enough that little game time is lost.
    """
    name = "queue_flush"
    out: dict[str, Any] = {}
    server = await _spawn(name, {"construction.command_pause_level": "1"}, game_port)
    try:
        await server.client.send_rcon("unpause")
        await asyncio.sleep(2.0)
        target = await _pick_build_tile(server)
        out["target"] = target
        if target is None:
            out["error"] = "no road-adjacent buildable tile found"
            return out

        # --- PAUSE: deliberate. Only dry-runs and reads happen here. ---
        await server.client.send_rcon("pause")
        await asyncio.sleep(1.0)
        date_at_pause = (await _game_date(server)).get("date")

        stop_params = {
            "company_id": 0,
            "x": target["x"], "y": target["y"], "direction": target["direction"],
        }
        planned: list[dict[str, Any]] = [
            {"action": "set_loan", "params": {"company_id": 0, "amount": 200000}},
            {"action": "build_road_stop", "params": stop_params},
        ]

        # Validate the batch while paused, without committing it.
        validations = []
        for item in planned:
            est = await server.client.send_gamescript(
                "estimate_cost", {"action": item["action"], "params": item["params"]}, timeout=20.0
            )
            validations.append({
                "action": item["action"],
                "dry_run_success": bool(est.get("success")),
                "error": est.get("error"),
                "result": est.get("result"),
            })
        out["dry_runs_while_paused"] = validations

        # --- FLUSH: unpause, apply the batch, re-pause. Measure the cost. ---
        t0 = time.monotonic()
        await server.client.send_rcon("unpause")
        executed = []
        for item in planned:
            r = await server.client.send_gamescript(item["action"], item["params"], timeout=25.0)
            executed.append({
                "action": item["action"],
                "success": bool(r.get("success")),
                "error": r.get("error"),
                "result": r.get("result"),
            })
        await server.client.send_rcon("pause")
        flush_wall = time.monotonic() - t0
        date_after_flush = (await _game_date(server)).get("date")

        out["flush"] = {
            "executed": executed,
            "all_succeeded": all(e["success"] for e in executed),
            "flush_wall_seconds": round(flush_wall, 2),
            "game_days_lost_to_flush": (date_after_flush or 0) - (date_at_pause or 0),
            "date_at_pause": date_at_pause,
            "date_after_flush": date_after_flush,
        }
    finally:
        await _teardown(server)
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    results: dict[str, Any] = {}

    logger.info("=" * 78)
    logger.info("EXPERIMENT 1b -- build while paused (scan-derived target)")
    logger.info("=" * 78)
    for level, port in ((1, 4830), (3, 4840)):
        try:
            results[f"pause_level_{level}"] = await experiment_build_while_paused(level, port)
        except Exception as exc:
            logger.exception("pause level %d failed", level)
            results[f"pause_level_{level}"] = {"fatal_error": repr(exc)}

    logger.info("=" * 78)
    logger.info("EXPERIMENT 1c -- queue while paused, flush while running")
    logger.info("=" * 78)
    try:
        results["queue_and_flush"] = await experiment_queue_and_flush(4850)
    except Exception as exc:
        logger.exception("queue_and_flush failed")
        results["queue_and_flush"] = {"fatal_error": repr(exc)}

    logger.info("=" * 78)
    logger.info("EXPERIMENT 2b -- wallclock timekeeping rates")
    logger.info("=" * 78)
    try:
        results["wallclock"] = await experiment_wallclock_rates()
    except Exception as exc:
        logger.exception("wallclock failed")
        results["wallclock"] = {"fatal_error": repr(exc)}

    out = SCRATCH / "results_followup.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print("\n" + "=" * 78)
    print(json.dumps(results, indent=2, default=str))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())
