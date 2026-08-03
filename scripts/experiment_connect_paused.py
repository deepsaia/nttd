"""Does the long-running pathfinding build action work while paused?

connect_road / connect_rail run A* inside the GameScript and build as they go,
yielding every 500 iterations. They are the actions agents use most. If they
need game ticks to make progress, they may stall while the game is paused even
at command_pause_level = 3, where single-tile construction succeeds.

Usage:
    uv run python -m scripts.experiment_connect_paused
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

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)


async def run(pause_level: int, game_port: int) -> dict[str, Any]:
    """Build two bus stops and connect them by road, all while paused."""
    out: dict[str, Any] = {"pause_level": pause_level}
    server = await _spawn(
        f"connect_{pause_level}", {"construction.command_pause_level": str(pause_level)}, game_port
    )
    try:
        c = server.client
        out["setting"] = await _read_setting(server, "construction.command_pause_level")

        await c.send_rcon("unpause")
        await asyncio.sleep(2.0)

        towns = await c.send_gamescript("get_towns", timeout=25.0)
        tlist = [t for t in (towns.get("result") or []) if isinstance(t, dict)]
        if len(tlist) < 2:
            out["error"] = "need at least 2 towns"
            return out

        # Pick two towns reasonably close together to keep the path short.
        tlist.sort(key=lambda t: (t.get("x", 0), t.get("y", 0)))
        pairs = []
        for i in range(len(tlist) - 1):
            a, b = tlist[i], tlist[i + 1]
            d = abs(a.get("x", 0) - b.get("x", 0)) + abs(a.get("y", 0) - b.get("y", 0))
            if 8 <= d <= 30:
                pairs.append((d, a, b))
        if not pairs:
            out["error"] = "no suitable town pair"
            return out
        pairs.sort(key=lambda p: p[0])
        _, town_a, town_b = pairs[0]
        out["towns"] = {"a": town_a.get("name"), "b": town_b.get("name")}

        # Find stop spots for both while running. find_bus_stop_spots returns
        # nothing on these maps (a separate finder bug), so derive the target
        # from raw tile classification instead.
        deltas = [(1, 0), (0, 1), (-1, 0), (0, -1)]

        async def scan_spot(town: dict[str, Any]) -> dict[str, Any] | None:
            r = await c.send_gamescript(
                "scan_town_area", {"town_id": town.get("id"), "radius": 8}, timeout=30.0
            )
            res = r.get("result")
            if not isinstance(res, dict):
                return None
            buildable = {(t["x"], t["y"]) for t in res.get("buildable", []) if "x" in t}
            roads = {(t["x"], t["y"]) for t in res.get("roads", []) if "x" in t}
            for (bx, by) in sorted(buildable):
                for idx, (dx, dy) in enumerate(deltas):
                    if (bx + dx, by + dy) in roads:
                        return {"x": bx, "y": by, "direction": idx}
            return None

        spots: dict[str, Any] = {
            "a": await scan_spot(town_a),
            "b": await scan_spot(town_b),
        }
        out["spots"] = spots
        if not spots["a"] or not spots["b"]:
            out["error"] = "could not find bus stop spots"
            return out

        # --- PAUSE and do everything from here on while frozen. ---
        await c.send_rcon("pause")
        await asyncio.sleep(1.0)
        date_at_pause = (await _game_date(server)).get("date")

        await c.send_gamescript("set_loan", {"company_id": 0, "amount": 300000}, timeout=15.0)

        built = {}
        for label in ("a", "b"):
            s = spots[label]
            r = await c.send_gamescript(
                "build_road_stop",
                {
                    "company_id": 0, "x": s["x"], "y": s["y"],
                    "direction": s.get("direction", 0),
                },
                timeout=25.0,
            )
            built[label] = {"success": bool(r.get("success")), "error": r.get("error")}
        out["stops_built_while_paused"] = built

        # THE TEST: the long-running pathfinding build, while paused.
        t0 = time.monotonic()
        conn = await c.send_gamescript(
            "connect_road",
            {
                "company_id": 0,
                "from_x": spots["a"]["x"], "from_y": spots["a"]["y"],
                "to_x": spots["b"]["x"], "to_y": spots["b"]["y"],
            },
            timeout=180.0,
        )
        out["connect_road_while_paused"] = {
            "success": bool(conn.get("success")),
            "error": conn.get("error"),
            "elapsed_s": round(time.monotonic() - t0, 1),
            "result": conn.get("result"),
        }

        out["ping_after_connect_still_paused"] = (
            await c.send_gamescript("ping", timeout=10.0)
        ).get("success")
        date_after = (await _game_date(server)).get("date")
        out["game_days_elapsed_while_paused"] = (date_after or 0) - (date_at_pause or 0)
    finally:
        await _teardown(server)
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    results: dict[str, Any] = {}
    for level, port in ((3, 4930),):
        try:
            results[f"level_{level}"] = await run(level, port)
        except Exception as exc:
            logger.exception("level %d failed", level)
            results[f"level_{level}"] = {"fatal_error": repr(exc)}

    out = SCRATCH / "results_connect.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())
