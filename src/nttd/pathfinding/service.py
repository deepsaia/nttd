"""Pathfinding service: orchestrates tile loading and A* execution.

Derived from the OpenTTD multiplayer/agent study, §14.7 (local research notes, not in the repo).
"""

import logging
import time
from typing import Any

from nttd.pathfinding.astar import PathResult, find_path
from nttd.pathfinding.rail import RailCostFunction
from nttd.pathfinding.road import RoadCostFunction
from nttd.pathfinding.tile_cache import TileCache
from nttd.pathfinding.water import WaterCostFunction

logger = logging.getLogger(__name__)

# One cache per session, not one per process.
#
# A single nttd process hosts many sessions, and this held one cache created by whichever
# session pathfound first. The cache is not just a size: it holds height, slope,
# buildability, ownership and what is built for every tile. A second session on a
# different map would have planned routes across the first session's world.
#
# Not reachable by a contestant today, because connect_road and connect_rail pathfind
# inside the GameScript, per OpenTTD process. This route is operator-tier. Keyed anyway,
# because the next caller has no way to know that.
_caches: dict[str, TileCache] = {}


def get_cache(session_id: str) -> TileCache | None:
    return _caches.get(session_id)


def init_cache(session_id: str, map_width: int, map_height: int) -> TileCache:
    cache = TileCache(map_width, map_height)
    _caches[session_id] = cache
    return cache


def drop_cache(session_id: str) -> None:
    """Forget a session's tiles. A finished session's map is a few MB of nothing."""
    _caches.pop(session_id, None)


async def pathfind(
    session_id: str,
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    transport_type: str,
    gs_client: Any,
    company_id: int = -1,
    avoid_demolish: bool = False,
    max_iterations: int = 50_000,
    corridor_margin: int = 10,
) -> dict[str, Any]:
    """Find a path and return the result dict."""
    cache = _caches.get(session_id)
    if cache is None:
        return {"found": False, "error": "Tile cache not initialized"}

    t0 = time.monotonic()

    # Ensure corridor tiles are loaded
    loaded = await cache.load_corridor(
        gs_client, from_x, from_y, to_x, to_y, margin=corridor_margin,
    )
    logger.debug("Loaded %d tiles for corridor (%d,%d)->(%d,%d)", loaded, from_x, from_y, to_x, to_y)

    # Select cost function
    if transport_type == "road":
        cost_fn = RoadCostFunction(
            cache, avoid_demolish=avoid_demolish, company_id=company_id,
        )
    elif transport_type == "rail":
        cost_fn = RailCostFunction(
            cache, avoid_demolish=avoid_demolish, company_id=company_id,
        )
    elif transport_type == "water":
        cost_fn = WaterCostFunction(cache)
    else:
        return {"found": False, "error": f"Unknown transport_type: {transport_type}"}

    result: PathResult = find_path(
        from_x, from_y, to_x, to_y, cost_fn, max_iterations=max_iterations,
    )

    elapsed_ms = (time.monotonic() - t0) * 1000

    bridges = sum(1 for p in result.path if p.get("action") == "build_bridge")
    tunnels = sum(1 for p in result.path if p.get("action") == "build_tunnel")

    return {
        "found": result.found,
        "path": result.path,
        "total_cost": result.total_cost,
        "total_tiles": len(result.path),
        "bridges": bridges,
        "tunnels": tunnels,
        "tiles_explored": result.tiles_explored,
        "iterations": result.iterations,
        "estimated_time_ms": round(elapsed_ms, 1),
    }
