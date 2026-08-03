"""Two experiments that gate the benchmarking-platform design.

Experiment 1 -- Build-while-paused.
    Does OpenTTD accept construction commands while the game is paused?
    Run at construction.command_pause_level = 1 (the current base config value)
    and at 3 ("All actions"). This decides whether pause/step turn mode is
    viable at all.

Experiment 2 -- Runtime tunability of economy.minutes_per_calendar_year.
    Is the game-time-per-wall-time ratio settable at runtime via rcon, or only
    at map generation? This decides whether a short session can cover enough
    game years to be economically meaningful.

Both experiments spawn a real dedicated OpenTTD server on a scratch config
directory, drive it over the admin port, and tear it down. Nothing touches
logs/sessions/ or the committed ottd_config/.

Usage:
    uv run python scripts/experiment_pause_and_time.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nttd.bridge.admin_client import AdminClient  # noqa: E402
from nttd.runtime.config_builder import build_session_config  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)

REPO_ROOT = Path(__file__).parent.parent
BASE_CONFIG = REPO_ROOT / "ottd_config"
SCRATCH = REPO_ROOT / ".experiment_runs"
OPENTTD_BINARY = os.environ.get(
    "NTTD_OPENTTD_BINARY",
    "/Applications/OpenTTD.app/Contents/MacOS/openttd",
)
ADMIN_PASSWORD = "nttd"

# A small map keeps generation fast; flat terrain makes construction easy.
_SMALL_MAP_SETTINGS = {
    "game_creation.map_x": "8",
    "game_creation.map_y": "8",
    "game_creation.landscape": "0",
    "difficulty.terrain_type": "1",
    "difficulty.number_towns": "3",
    "difficulty.industry_density": "4",
    "game_creation.starting_year": "1960",
    "difficulty.max_no_competitors": "0",
}

_CONNECT_TIMEOUT = 40.0
_CONNECT_POLL = 0.5


@dataclass
class Server:
    """A running scratch OpenTTD server driven over the admin port."""

    name: str
    game_port: int
    admin_port: int
    client: AdminClient
    process: asyncio.subprocess.Process
    poll_task: asyncio.Task[None]
    session_dir: Path
    notes: list[str] = field(default_factory=list)


async def _spawn(name: str, extra_settings: dict[str, str], game_port: int) -> Server:
    """Spawn a dedicated OpenTTD server with the given extra cfg settings.

    One company slot is provisioned so construction has an owner (company 0).
    """
    session_dir = SCRATCH / name
    if session_dir.exists():
        shutil.rmtree(session_dir)

    admin_port = game_port + 1
    settings = dict(_SMALL_MAP_SETTINGS)
    settings.update(extra_settings)

    build_session_config(
        base_config_dir=BASE_CONFIG,
        session_dir=session_dir,
        game_port=game_port,
        admin_port=admin_port,
        admin_password=ADMIN_PASSWORD,
        settings=settings,
        agent_companies=1,
    )

    cfg_path = str(session_dir / "openttd.cfg")
    logger.info("[%s] spawning openttd -D -c %s", name, cfg_path)
    process = await asyncio.create_subprocess_exec(
        OPENTTD_BINARY, "-D", "-c", cfg_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    client = AdminClient(host="127.0.0.1", port=admin_port)
    deadline = time.time() + _CONNECT_TIMEOUT
    while time.time() < deadline:
        if await client.connect(password=ADMIN_PASSWORD, name=f"exp_{name}"):
            break
        await asyncio.sleep(_CONNECT_POLL)
    else:
        process.kill()
        raise RuntimeError(f"[{name}] admin port never came up")

    poll_task = asyncio.create_task(client.poll_loop(), name=f"poll_{name}")
    await client.subscribe_defaults()

    # Wait for the GameScript to answer -- it compiles on startup.
    for _ in range(40):
        r = await client.send_gamescript("ping", timeout=5.0)
        if r.get("success"):
            break
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError(f"[{name}] GameScript never responded to ping")

    logger.info("[%s] up (game=%d admin=%d pid=%s)", name, game_port, admin_port, process.pid)
    return Server(name, game_port, admin_port, client, process, poll_task, session_dir)


async def _teardown(server: Server) -> None:
    """Stop the server and clean up its scratch directory."""
    try:
        await server.client.disconnect()
    except Exception:
        logger.debug("[%s] disconnect failed", server.name)
    server.poll_task.cancel()
    try:
        server.process.terminate()
        await asyncio.wait_for(server.process.wait(), timeout=8.0)
    except Exception:
        server.process.kill()
    logger.info("[%s] torn down", server.name)


async def _read_setting(server: Server, key: str) -> str:
    """Read a setting value via rcon `setting <key>`."""
    lines = await server.client.send_rcon(f"setting {key}")
    return " | ".join(line.strip() for line in lines if line.strip())


async def _game_date(server: Server) -> dict[str, Any]:
    r = await server.client.send_gamescript("get_date", timeout=10.0)
    return r.get("result") or {}


async def _find_build_spot(server: Server) -> dict[str, Any] | None:
    """Find a validated bus-stop spot in town 0 -- used as the build target."""
    r = await server.client.send_gamescript(
        "find_bus_stop_spots", {"company_id": 0, "town_id": 0, "max_results": 5}, timeout=25.0
    )
    spots = r.get("result") if r.get("success") else None
    if isinstance(spots, list) and spots:
        return spots[0]
    return None


# ---------------------------------------------------------------------------
# Experiment 1: build while paused
# ---------------------------------------------------------------------------

async def experiment_build_while_paused(pause_level: int, game_port: int) -> dict[str, Any]:
    """Try a construction command while paused at the given command_pause_level."""
    name = f"pause_level_{pause_level}"
    result: dict[str, Any] = {"pause_level": pause_level}
    server = await _spawn(
        name,
        {"construction.command_pause_level": str(pause_level)},
        game_port,
    )
    try:
        result["setting_readback"] = await _read_setting(server, "construction.command_pause_level")

        # A company is required to own construction. Start one AI-free company
        # by asking the GS which companies exist; the cfg gives us company 0.
        companies = await server.client.send_gamescript("get_companies", timeout=10.0)
        result["companies"] = companies.get("result")

        spot = await _find_build_spot(server)
        if spot is None:
            result["error"] = "no buildable bus-stop spot found; cannot test"
            return result
        result["spot"] = spot

        # Baseline: confirm the build works while RUNNING.
        await server.client.send_rcon("unpause")
        await asyncio.sleep(1.0)
        date_before = await _game_date(server)
        await asyncio.sleep(3.0)
        date_after = await _game_date(server)
        result["clock_runs_when_unpaused"] = (
            date_after.get("date", 0) > date_before.get("date", 0)
        )

        # Now pause and verify the clock is actually frozen.
        await server.client.send_rcon("pause")
        await asyncio.sleep(1.0)
        paused_before = await _game_date(server)
        await asyncio.sleep(3.0)
        paused_after = await _game_date(server)
        result["clock_frozen_when_paused"] = (
            paused_after.get("date", 0) == paused_before.get("date", 0)
        )

        # THE TEST: build while paused.
        build_params = {
            "company_id": 0,
            "x": spot.get("x"),
            "y": spot.get("y"),
            "direction": spot.get("direction", 0),
        }
        build = await server.client.send_gamescript("build_road_stop", build_params, timeout=20.0)
        result["build_while_paused"] = {
            "success": bool(build.get("success")),
            "error": build.get("error"),
            "raw": build,
        }

        # Also test a non-construction command while paused, for contrast.
        loan = await server.client.send_gamescript(
            "set_loan", {"company_id": 0, "amount": 100000}, timeout=15.0
        )
        result["nonconstruction_while_paused"] = {
            "success": bool(loan.get("success")),
            "error": loan.get("error"),
        }

        # And confirm the same build shape works once unpaused, so a failure
        # above is attributable to pause rather than to a bad tile.
        if not build.get("success"):
            await server.client.send_rcon("unpause")
            await asyncio.sleep(2.0)
            retry = await server.client.send_gamescript(
                "build_road_stop", build_params, timeout=20.0
            )
            result["same_build_while_running"] = {
                "success": bool(retry.get("success")),
                "error": retry.get("error"),
            }
    finally:
        await _teardown(server)
    return result


# ---------------------------------------------------------------------------
# Experiment 2: runtime tunability of minutes_per_calendar_year
# ---------------------------------------------------------------------------

async def experiment_minutes_per_year(game_port: int) -> dict[str, Any]:
    """Measure game-day rate, change minutes_per_calendar_year at runtime, re-measure."""
    name = "minutes_per_year"
    result: dict[str, Any] = {}
    server = await _spawn(name, {"economy.minutes_per_calendar_year": "12"}, game_port)
    try:
        result["initial_setting"] = await _read_setting(server, "economy.minutes_per_calendar_year")
        result["timekeeping_units"] = await _read_setting(server, "economy.timekeeping_units")

        await server.client.send_rcon("unpause")
        await asyncio.sleep(2.0)

        async def measure(label: str, seconds: float) -> dict[str, Any]:
            """Measure elapsed game days over a wall-clock window."""
            d0 = await _game_date(server)
            t0 = time.monotonic()
            await asyncio.sleep(seconds)
            d1 = await _game_date(server)
            wall = time.monotonic() - t0
            days = d1.get("date", 0) - d0.get("date", 0)
            rate = wall / days if days else float("inf")
            logger.info(
                "[%s] %s: %d game-days in %.1fs -> %.3f s/day (%.1f min/game-year)",
                name, label, days, wall, rate, rate * 365 / 60,
            )
            return {
                "game_days": days,
                "wall_seconds": round(wall, 2),
                "seconds_per_game_day": round(rate, 3) if days else None,
                "implied_minutes_per_game_year": round(rate * 365 / 60, 2) if days else None,
                "date_from": d0.get("date"),
                "date_to": d1.get("date"),
            }

        result["baseline_at_12"] = await measure("baseline (12 min/yr)", 20.0)

        # Try to change it at runtime.
        rcon_out = await server.client.send_rcon("setting economy.minutes_per_calendar_year 1")
        result["rcon_set_to_1"] = [line.strip() for line in rcon_out if line.strip()]
        await asyncio.sleep(1.0)
        result["setting_after_rcon"] = await _read_setting(
            server, "economy.minutes_per_calendar_year"
        )

        result["after_set_to_1"] = await measure("after set to 1 min/yr", 20.0)

        # Also try the GS route, which is a different code path than rcon.
        gs = await server.client.send_gamescript(
            "set_game_setting",
            {"key": "economy.minutes_per_calendar_year", "value": 3},
            timeout=15.0,
        )
        result["gs_set_game_setting"] = {"success": bool(gs.get("success")), "error": gs.get("error")}
        await asyncio.sleep(1.0)
        result["setting_after_gs"] = await _read_setting(
            server, "economy.minutes_per_calendar_year"
        )
        result["after_gs_set_to_3"] = await measure("after GS set to 3 min/yr", 20.0)
    finally:
        await _teardown(server)
    return result


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    results: dict[str, Any] = {}

    logger.info("=" * 78)
    logger.info("EXPERIMENT 1 -- build while paused")
    logger.info("=" * 78)
    for level, port in ((1, 4600), (3, 4610)):
        try:
            results[f"pause_level_{level}"] = await experiment_build_while_paused(level, port)
        except Exception as exc:
            logger.exception("pause level %d failed", level)
            results[f"pause_level_{level}"] = {"fatal_error": repr(exc)}

    logger.info("=" * 78)
    logger.info("EXPERIMENT 2 -- minutes_per_calendar_year runtime tunability")
    logger.info("=" * 78)
    try:
        results["minutes_per_year"] = await experiment_minutes_per_year(4620)
    except Exception as exc:
        logger.exception("minutes_per_year failed")
        results["minutes_per_year"] = {"fatal_error": repr(exc)}

    import json
    out = SCRATCH / "results.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)
    print(json.dumps(results, indent=2, default=str))
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    asyncio.run(main())
