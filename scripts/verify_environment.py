"""Re-verify the OpenTTD behaviours nttd's design depends on.

nttd makes several load-bearing claims about OpenTTD 15.3 that are not documented by
OpenTTD and were established by measurement. Each is recorded as a comment where it
matters, but a comment cannot notice when an OpenTTD upgrade invalidates it. This
re-runs the measurements.

Not a test suite: it needs a real OpenTTD binary and takes minutes. Run it after
changing OpenTTD version, the GameScript, or the base config.

    uv run python -m scripts.verify_environment

Replaces eleven single-question experiment scripts. Their findings are all recorded
in the code they justify -- the seed flag in runtime/session_runtime.py, the terrain
enum in config/benchmark_profile.py, the pause behaviour in runtime/orchestrator.py
and ottd_config/openttd.cfg -- so what was worth keeping was the ability to re-check
them, not eleven copies of the harness.

What is checked, and what breaks if it stops holding:

  1. SEED DETERMINISM. Only the -G flag pins generation; the cfg key alone does not.
     If this fails, two contestants on the same declared task face different worlds
     and the leaderboard compares nothing.

  2. ECONOMY CLOCK RATE. Fixed at 1 wall-minute per economy month, roughly 1.97s per
     game-day. The tier definitions are derived from it: T2 is 30 minutes BECAUSE
     that is 2.5 game years.

  3. ENGINE AVAILABILITY at the profile's start year. A start year with no buildable
     vehicles for some mode would make that mode unplayable without any error.

  4. ACTIONS WHILE PAUSED. construction.command_pause_level = 3 must let a paused
     build succeed. At level 1 it times out, wedges the GameScript, and has actually
     executed -- so nttd would record a failure for an action that changed the world.

  5. LONG PATHFINDING DEADLOCKS WHILE PAUSED, at any pause level, because the A*
     yields through Sleep(1) and Sleep counts game ticks. Length decides it: a
     short connect_road succeeds while paused in 0.0s, a cross-map one hangs. So
     it cannot be predicted from the action, and the step barrier flushes its
     whole batch unpaused rather than while the world is still.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nttd.bridge.admin_client import AdminClient  # noqa: E402
from nttd.runtime.config_builder import build_session_config  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("verify")
logger.setLevel(logging.INFO)

REPO_ROOT = Path(__file__).parent.parent
BASE_CONFIG = REPO_ROOT / "ottd_config"
SCRATCH = REPO_ROOT / ".verify_runs"
ADMIN_PASSWORD = "nttd"
OPENTTD_BINARY = os.environ.get(
    "NTTD_OPENTTD_BINARY", "/Applications/OpenTTD.app/Contents/MacOS/openttd",
)

# A 64x64 map generates in a couple of seconds, which keeps the checks that only
# read state short.
_SMALL_MAP: dict[str, str] = {
    "game_creation.map_x": "6",
    "game_creation.map_y": "6",
    "difficulty.max_no_competitors": "0",
    "game_creation.starting_year": "2020",
}

# The build and pathfinding checks need real towns with road frontage, which a 64x64
# map does not reliably produce -- the first pass failed on "no buildable spot" and
# "need two towns", which was the harness being too small rather than OpenTTD
# misbehaving. 256x256 with many towns is what the shipped scenarios use anyway.
_BUILDABLE_MAP: dict[str, str] = {
    "game_creation.map_x": "8",
    "game_creation.map_y": "8",
    "game_creation.starting_year": "2020",
    "difficulty.number_towns": "3",
    # A company must exist, or find_bus_stop_spots returns nothing: the finder
    # dry-runs each tile under a company's road-type context, so with no company
    # every candidate is rejected and the check reads it as "no buildable spot".
    # OpenTTD creates company slots from max_no_competitors during generation.
    "difficulty.max_no_competitors": "1",
    "difficulty.competitors_interval": "0",
    "ai_in_multiplayer": "true",
}

# Below this, a connect_road failure is a bad request rather than the
# Sleep(1) deadlock the check is asserting.
# The company slot OpenTTD creates from max_no_competitors.
_COMPANY_ID = 0

_DEADLOCK_MIN_SECONDS = 20.0

_SECS_PER_GAME_DAY_EXPECTED = 1.97
_VEHICLE_TYPES = ("train", "road", "ship", "aircraft")


class Server:
    """A scratch OpenTTD server with a connected admin client."""

    def __init__(self, name: str, port: int) -> None:
        self.name = name
        self.game_port = port
        self.admin_port = port + 1
        self.process: asyncio.subprocess.Process | None = None
        self.client = AdminClient(host="127.0.0.1", port=self.admin_port)
        self._poll: asyncio.Task[Any] | None = None

    async def start(self, settings: dict[str, str] | None = None, seed: int | None = None) -> None:
        session_dir = SCRATCH / self.name
        if session_dir.exists():
            shutil.rmtree(session_dir)
        merged = dict(_SMALL_MAP)
        merged.update(settings or {})
        build_session_config(
            base_config_dir=BASE_CONFIG,
            session_dir=session_dir,
            game_port=self.game_port,
            admin_port=self.admin_port,
            admin_password=ADMIN_PASSWORD,
            settings=merged,
        )
        argv = [OPENTTD_BINARY, "-D", "-c", str(session_dir / "openttd.cfg")]
        if seed is not None:
            argv += ["-G", str(seed)]
        self.process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        deadline = time.time() + 60.0
        while time.time() < deadline:
            if await self.client.connect(password=ADMIN_PASSWORD, name=f"verify_{self.name}"):
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError(f"[{self.name}] admin port never came up")

        self._poll = asyncio.create_task(self.client.poll_loop(), name=f"poll_{self.name}")
        await self.client.subscribe_defaults()
        for _ in range(60):
            if (await self.client.send_gamescript("ping", timeout=5.0)).get("success"):
                return
            await asyncio.sleep(0.5)
        raise RuntimeError(f"[{self.name}] GameScript never answered")

    async def gs(self, action: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        return await self.client.send_gamescript(action, params or {}, timeout=timeout)

    async def date(self) -> int:
        reply = await self.gs("get_date")
        return int((reply.get("result") or {}).get("date", 0))

    async def stop(self) -> None:
        if self._poll is not None:
            self._poll.cancel()
        await self.client.disconnect()
        if self.process is not None:
            self.process.terminate()
            await self.process.wait()


async def check_seed_determinism() -> dict[str, Any]:
    """Two servers on the same seed must generate the same world."""
    digests: list[str] = []
    for index in range(2):
        server = Server(f"seed{index}", 3990 + index * 10)
        try:
            await server.start(seed=4242)
            towns = (await server.gs("get_towns", timeout=60.0)).get("result") or []
            fingerprint = json.dumps(
                sorted((t.get("x"), t.get("y"), t.get("name")) for t in towns),
                separators=(",", ":"),
            )
            digests.append(hashlib.sha256(fingerprint.encode()).hexdigest()[:16])
        finally:
            await server.stop()

    return {
        "check": "seed determinism (-G)",
        "passed": len(set(digests)) == 1 and bool(digests[0]),
        "detail": f"digests {digests}",
    }


async def check_clock_rate() -> dict[str, Any]:
    """The economy clock must advance at the rate the tiers are derived from."""
    server = Server("clock", 4010)
    try:
        await server.start(seed=4242)
        start = await server.date()
        await asyncio.sleep(20.0)
        elapsed_days = await server.date() - start
        rate = 20.0 / elapsed_days if elapsed_days else 0.0
        # Generous band: the point is to catch a version that changes the rate, not
        # to police scheduler jitter.
        passed = elapsed_days > 0 and abs(rate - _SECS_PER_GAME_DAY_EXPECTED) < 0.6
        return {
            "check": "economy clock rate",
            "passed": passed,
            "detail": f"{elapsed_days} game-days in 20s = {rate:.2f}s/day "
                      f"(expected ~{_SECS_PER_GAME_DAY_EXPECTED})",
        }
    finally:
        await server.stop()


async def check_engine_availability() -> dict[str, Any]:
    """Every transport mode must have something buildable at the profile's year."""
    server = Server("engines", 4020)
    try:
        await server.start(seed=4242)
        counts: dict[str, int] = {}
        for vehicle_type in _VEHICLE_TYPES:
            reply = await server.gs("get_engines", {"vehicle_type": vehicle_type}, timeout=30.0)
            listed = reply.get("result")
            counts[vehicle_type] = len(listed) if isinstance(listed, list) else -1
        return {
            "check": "engine availability at 2020",
            "passed": all(count > 0 for count in counts.values()),
            "detail": ", ".join(f"{name}={count}" for name, count in counts.items()),
        }
    finally:
        await server.stop()


async def _find_distant_tiles(server: Server) -> list[int]:
    """Two buildable tiles far apart, so the A* is forced to yield.

    Distance matters. The pathfinder only reaches its Sleep(1) yield every 500
    iterations, so a SHORT connection completes while paused without ever yielding:
    two adjacent spots in one town returned success in 0.0s. Only a path long enough
    to yield deadlocks, which is the case worth asserting.
    """
    towns = (await server.gs("get_towns", timeout=60.0)).get("result") or []
    if len(towns) < 2:
        return []
    # Widest separation available, by Manhattan distance on town coordinates.
    best: tuple[int, Any, Any] | None = None
    for i, first in enumerate(towns):
        for second in towns[i + 1:]:
            distance = abs(first.get("x", 0) - second.get("x", 0)) + abs(
                first.get("y", 0) - second.get("y", 0)
            )
            if best is None or distance > best[0]:
                best = (distance, first, second)
    if best is None:
        return []

    tiles: list[int] = []
    for town in (best[1], best[2]):
        spots = (await server.gs(
            "find_bus_stop_spots",
            {"town_id": town["id"], "max_results": 1, "company_id": _COMPANY_ID},
            timeout=90.0,
        )).get("result") or []
        if spots and spots[0].get("tile"):
            tiles.append(spots[0]["tile"])
    logger.info("distant pair separated by %d tiles", best[0])
    return tiles


async def _find_buildable_tiles(server: Server, wanted: int = 2) -> list[int]:
    """Return tile indices the GameScript itself says are buildable.

    Asks across towns rather than trusting the first: not every town has road
    frontage, and picking towns[0] made the build check report "no buildable spot"
    as though OpenTTD had changed. Using GS-supplied indices also avoids computing
    TileIndex by hand, which is y * map_width + x -- getting that transposed made
    connect_road fail instantly on an invalid tile, and the pathfinding check read
    the fast failure as the deadlock it was looking for.
    """
    towns = (await server.gs("get_towns", timeout=60.0)).get("result") or []
    tiles: list[int] = []
    for town in towns[:8]:
        spots = (await server.gs(
            "find_bus_stop_spots",
            {"town_id": town["id"], "max_results": 2, "company_id": _COMPANY_ID},
            timeout=90.0,
        )).get("result") or []
        tiles.extend(spot["tile"] for spot in spots if spot.get("tile"))
        if len(tiles) >= wanted:
            break
    return tiles[:wanted]


async def check_paused_build() -> dict[str, Any]:
    """A paused single-tile build must succeed at command_pause_level = 3."""
    server = Server("paused", 4030)
    try:
        await server.start(settings=_BUILDABLE_MAP, seed=4242)
        tiles = await _find_buildable_tiles(server, wanted=1)
        if not tiles:
            return {"check": "build while paused", "passed": False,
                    "detail": "no buildable spot in the first 8 towns"}

        await server.client.send_rcon("pause")
        await asyncio.sleep(1.0)
        started = time.time()
        reply = await server.gs(
            # company_id is required: the GS wraps every build in
            # GSCompanyMode(p.company_id), and without one the command has no
            # company to act for and fails instantly.
            "build_road_stop",
            {"tile": tiles[0], "is_truck": False, "company_id": _COMPANY_ID},
            timeout=30.0,
        )
        elapsed = time.time() - started
        alive = (await server.gs("ping", timeout=10.0)).get("success")
        await server.client.send_rcon("unpause")

        return {
            "check": "build while paused (level 3)",
            "passed": bool(reply.get("success")) and bool(alive),
            "detail": f"success={reply.get('success')} in {elapsed:.1f}s, "
                      f"gs_alive={alive}. At level 1 this times out, wedges the GS, "
                      f"and has already executed.",
        }
    finally:
        await server.stop()


async def check_paused_pathfinding_deadlocks() -> dict[str, Any]:
    """connect_road must NOT complete while paused, at any pause level.

    Asserting a deadlock rather than hoping for one: the step barrier unpauses before
    flushing precisely because of it, so if a future OpenTTD or GameScript made
    pathfinding work while paused, the barrier could be simplified.
    """
    server = Server("pathfind", 4040)
    try:
        await server.start(settings=_BUILDABLE_MAP, seed=4242)
        tiles = await _find_distant_tiles(server)
        if len(tiles) < 2:
            return {"check": "pathfinding deadlocks while paused", "passed": False,
                    "detail": "need two distant buildable tiles"}

        await server.client.send_rcon("pause")
        await asyncio.sleep(1.0)
        started = time.time()
        reply = await server.gs(
            "connect_road",
            {"tile_from": tiles[0], "tile_to": tiles[1], "company_id": _COMPANY_ID},
            timeout=25.0,
        )
        elapsed = time.time() - started
        alive = (await server.gs("ping", timeout=10.0)).get("success")
        await server.client.send_rcon("unpause")

        # A deadlock means it HUNG, not that it returned an error. An instant
        # failure is a bad request and would otherwise be misread as the very
        # behaviour this is asserting.
        hung = not reply.get("success") and elapsed >= _DEADLOCK_MIN_SECONDS
        return {
            "check": "pathfinding deadlocks while paused",
            "passed": hung,
            "detail": f"success={reply.get('success')} after {elapsed:.0f}s "
                      f"(a deadlock must take >= {_DEADLOCK_MIN_SECONDS:.0f}s; a fast "
                      f"failure is a bad request, not the Sleep(1) deadlock), "
                      f"gs_alive={alive} err={(reply.get('error') or '')[:60]!r}",
        }
    finally:
        await server.stop()


async def main() -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    checks = (
        check_seed_determinism,
        check_clock_rate,
        check_engine_availability,
        check_paused_build,
        check_paused_pathfinding_deadlocks,
    )

    results: list[dict[str, Any]] = []
    for check in checks:
        logger.info("running %s", check.__name__)
        try:
            results.append(await check())
        except Exception as exc:
            logger.exception("%s raised", check.__name__)
            results.append({
                "check": check.__name__, "passed": False, "detail": f"raised {exc!r}",
            })

    print("\n=== environment verification ===")
    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"  [{mark}] {result['check']}")
        print(f"         {result['detail']}")

    failed = [r for r in results if not r["passed"]]
    if failed:
        print(f"\n{len(failed)} check(s) failed. nttd's design assumes these hold; a "
              f"failure means a comment somewhere is now wrong.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
