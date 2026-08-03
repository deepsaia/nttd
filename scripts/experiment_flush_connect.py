"""Validate the queue-and-flush turn design against the workhorse action.

Single-tile construction succeeds while paused at command_pause_level = 3, but
connect_road does not: it yields via Sleep(1) between A* chunks, and Sleep needs
game ticks that a paused game never delivers.

The queue-and-flush design sidesteps this: deliberate while paused, then unpause
only long enough to apply the batch, then re-pause. This measures what that flush
window actually costs in game days for a batch that includes connect_road.

Usage:
    uv run python -m scripts.experiment_flush_connect
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
    _spawn,
    _teardown,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)

_DELTAS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


async def _scan_spot(server: Server, town_id: int) -> dict[str, Any] | None:
    """Return a buildable tile adjacent to a road, with the facing direction."""
    r = await server.client.send_gamescript(
        "scan_town_area", {"town_id": town_id, "radius": 8}, timeout=30.0
    )
    res = r.get("result")
    if not isinstance(res, dict):
        return None
    buildable = {(t["x"], t["y"]) for t in res.get("buildable", []) if "x" in t}
    roads = {(t["x"], t["y"]) for t in res.get("roads", []) if "x" in t}
    for (bx, by) in sorted(buildable):
        for idx, (dx, dy) in enumerate(_DELTAS):
            if (bx + dx, by + dy) in roads:
                return {"x": bx, "y": by, "direction": idx}
    return None


async def run(game_port: int) -> dict[str, Any]:
    """Deliberate paused, flush a batch containing connect_road, re-pause."""
    out: dict[str, Any] = {}
    server = await _spawn(
        "flush_connect", {"construction.command_pause_level": "3"}, game_port
    )
    try:
        c = server.client
        await c.send_rcon("unpause")
        await asyncio.sleep(2.0)

        towns = [t for t in ((await c.send_gamescript("get_towns", timeout=25.0)).get("result") or [])
                 if isinstance(t, dict)]
        towns.sort(key=lambda t: (t.get("x", 0), t.get("y", 0)))
        pair = None
        for i in range(len(towns) - 1):
            a, b = towns[i], towns[i + 1]
            d = abs(a.get("x", 0) - b.get("x", 0)) + abs(a.get("y", 0) - b.get("y", 0))
            if 8 <= d <= 25:
                pair = (a, b)
                break
        if pair is None:
            out["error"] = "no suitable town pair"
            return out
        town_a, town_b = pair
        out["towns"] = {"a": town_a.get("name"), "b": town_b.get("name")}

        spot_a = await _scan_spot(server, town_a.get("id"))
        spot_b = await _scan_spot(server, town_b.get("id"))
        out["spots"] = {"a": spot_a, "b": spot_b}
        if not spot_a or not spot_b:
            out["error"] = "could not derive spots"
            return out

        # --- PAUSE: this is where an agent would deliberate. ---
        await c.send_rcon("pause")
        await asyncio.sleep(1.0)
        date_at_pause = (await _game_date(server)).get("date")
        t_pause_start = time.monotonic()

        batch: list[dict[str, Any]] = [
            {"action": "set_loan", "params": {"company_id": 0, "amount": 300000}},
            {"action": "build_road_stop", "params": {"company_id": 0, **spot_a}},
            {"action": "build_road_stop", "params": {"company_id": 0, **spot_b}},
            {"action": "connect_road", "params": {
                "company_id": 0,
                "from_x": spot_a["x"], "from_y": spot_a["y"],
                "to_x": spot_b["x"], "to_y": spot_b["y"],
            }},
        ]

        # Dry-run the cheap ones while paused to show validation is free.
        dry = []
        for item in batch[:3]:
            est = await c.send_gamescript(
                "estimate_cost", {"action": item["action"], "params": item["params"]}, timeout=20.0
            )
            dry.append({
                "action": item["action"],
                "success": bool(est.get("success")),
                "estimated_cost": (est.get("result") or {}).get("estimated_cost"),
                "error": est.get("error"),
            })
        out["dry_runs_while_paused"] = dry
        out["deliberation_wall_seconds"] = round(time.monotonic() - t_pause_start, 2)
        out["game_days_during_deliberation"] = (
            ((await _game_date(server)).get("date") or 0) - (date_at_pause or 0)
        )

        # --- FLUSH: unpause, apply the whole batch, re-pause. ---
        date_before_flush = (await _game_date(server)).get("date")
        t0 = time.monotonic()
        await c.send_rcon("unpause")
        executed = []
        for item in batch:
            timeout = 180.0 if item["action"].startswith("connect_") else 25.0
            ts = time.monotonic()
            r = await c.send_gamescript(item["action"], item["params"], timeout=timeout)
            executed.append({
                "action": item["action"],
                "success": bool(r.get("success")),
                "error": r.get("error"),
                "elapsed_s": round(time.monotonic() - ts, 1),
                "result_keys": list((r.get("result") or {}).keys())
                if isinstance(r.get("result"), dict) else None,
            })
        await c.send_rcon("pause")
        flush_wall = time.monotonic() - t0
        date_after_flush = (await _game_date(server)).get("date")

        out["flush"] = {
            "executed": executed,
            "all_succeeded": all(e["success"] for e in executed),
            "flush_wall_seconds": round(flush_wall, 1),
            "game_days_lost_to_flush": (date_after_flush or 0) - (date_before_flush or 0),
        }
    finally:
        await _teardown(server)
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    try:
        results = {"flush_connect": await run(4950)}
    except Exception as exc:
        logger.exception("failed")
        results = {"flush_connect": {"fatal_error": repr(exc)}}
    out = SCRATCH / "results_flush_connect.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())
