"""Confirm two specific behaviours found in the pause/time experiments.

Test A -- does a construction command issued while paused at
    command_pause_level = 1 merely FAIL, or does it WEDGE the GameScript?
    A suspended ScriptObject command waiting for a confirmation that never
    arrives while paused would be a much worse failure mode than a clean
    rejection, so this distinction matters operationally.

Test B -- in wallclock timekeeping, does GSDate report the CALENDAR clock
    (tunable via minutes_per_calendar_year) or the ECONOMY clock (fixed at
    1 minute per economy month)? This decides whether there is any lever at
    all on how much economic simulation a bounded session can cover.

Usage:
    uv run python -m scripts.experiment_pause_wedge
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
    _game_date,
    _read_setting,
    _spawn,
    _teardown,
)
from scripts.experiment_wallclock_and_pause import _pick_build_tile  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)


async def test_pause_wedge(game_port: int) -> dict[str, Any]:
    """At pause level 1: build while paused, then check whether the GS recovers."""
    out: dict[str, Any] = {}
    server = await _spawn("wedge", {"construction.command_pause_level": "1"}, game_port)
    try:
        out["pause_level"] = await _read_setting(server, "construction.command_pause_level")
        c = server.client

        await c.send_rcon("unpause")
        await asyncio.sleep(2.0)
        target = await _pick_build_tile(server)
        out["target"] = target
        if target is None:
            out["error"] = "no target found"
            return out
        params = {
            "company_id": 0,
            "x": target["x"], "y": target["y"], "direction": target["direction"],
        }

        # Health check BEFORE the paused build.
        out["ping_before"] = (await c.send_gamescript("ping", timeout=5.0)).get("success")

        await c.send_rcon("pause")
        await asyncio.sleep(1.0)

        t0 = time.monotonic()
        build = await c.send_gamescript("build_road_stop", params, timeout=15.0)
        out["build_while_paused"] = {
            "success": bool(build.get("success")),
            "error": build.get("error"),
            "elapsed_s": round(time.monotonic() - t0, 2),
        }

        # Is the GS still answering while still paused?
        out["ping_after_paused_build_still_paused"] = (
            await c.send_gamescript("ping", timeout=8.0)
        ).get("success")

        # Unpause and see whether the GS recovers, and whether the wedged
        # command lands late (which would be a correctness problem: an action
        # reported as failed that actually executes).
        await c.send_rcon("unpause")
        await asyncio.sleep(4.0)
        out["ping_after_unpause"] = (await c.send_gamescript("ping", timeout=10.0)).get("success")

        stations = await c.send_gamescript("get_stations", {"company_id": 0}, timeout=15.0)
        slist = stations.get("result")
        out["stations_after_unpause"] = {
            "count": len(slist) if isinstance(slist, list) else None,
            "detail": slist if isinstance(slist, list) else slist,
        }
        out["late_landing_of_failed_action"] = bool(
            isinstance(slist, list) and len(slist) > 0
        )

        retry = await c.send_gamescript("build_road_stop", params, timeout=20.0)
        out["retry_while_running"] = {
            "success": bool(retry.get("success")), "error": retry.get("error"),
        }
    finally:
        await _teardown(server)
    return out


async def test_which_clock(game_port: int) -> dict[str, Any]:
    """In wallclock mode at 1 min/calendar-year, see which clock GSDate follows."""
    out: dict[str, Any] = {}
    server = await _spawn(
        "which_clock",
        {"economy.timekeeping_units": "1", "economy.minutes_per_calendar_year": "1"},
        game_port,
    )
    try:
        out["timekeeping"] = await _read_setting(server, "economy.timekeeping_units")
        out["minutes_per_calendar_year"] = await _read_setting(
            server, "economy.minutes_per_calendar_year"
        )
        await server.client.send_rcon("unpause")
        await asyncio.sleep(2.0)

        # At 1 min/calendar-year, a CALENDAR clock advances ~365 days/minute.
        # An ECONOMY clock advances ~30 days/minute (1 min = 1 economy month).
        d0 = await _game_date(server)
        t0 = time.monotonic()
        await asyncio.sleep(65.0)
        d1 = await _game_date(server)
        wall = time.monotonic() - t0
        days = (d1.get("date") or 0) - (d0.get("date") or 0)

        out["observed"] = {
            "wall_seconds": round(wall, 1),
            "days_elapsed": days,
            "from": {k: d0.get(k) for k in ("date", "year", "month", "day")},
            "to": {k: d1.get(k) for k in ("date", "year", "month", "day")},
            "days_per_wall_minute": round(days / (wall / 60.0), 1),
        }
        # ~365/min => calendar clock; ~30/min => economy clock.
        out["verdict"] = (
            "GSDate follows the CALENDAR clock (tunable)" if days > 200
            else "GSDate follows the ECONOMY clock (fixed at 1 min = 1 economy month)"
        )
    finally:
        await _teardown(server)
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    results: dict[str, Any] = {}

    logger.info("TEST A -- does pause level 1 wedge the GameScript?")
    try:
        results["pause_wedge"] = await test_pause_wedge(4900)
    except Exception as exc:
        logger.exception("wedge test failed")
        results["pause_wedge"] = {"fatal_error": repr(exc)}

    logger.info("TEST B -- which clock does GSDate report in wallclock mode?")
    try:
        results["which_clock"] = await test_which_clock(4910)
    except Exception as exc:
        logger.exception("clock test failed")
        results["which_clock"] = {"fatal_error": repr(exc)}

    out = SCRATCH / "results_wedge.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())
