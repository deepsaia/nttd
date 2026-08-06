"""Water pathfinder: A* on water tiles + canal construction.

Existing water is free to traverse. Land tiles require canal construction.

Derived from the OpenTTD multiplayer/agent study, §14.5 (local research notes, not in the repo).
"""

from nttd.pathfinding.astar import PathNode
from nttd.pathfinding.tile_cache import TileCache, TileData

COST_WATER: int = 50
COST_CANAL: int = 500
COST_COAST: int = 100
COST_LOCK: int = 800

_DIRS: list[tuple[int, int]] = [(0, -1), (1, 0), (0, 1), (-1, 0)]


class WaterCostFunction:
    """Cost function for water/canal pathfinding."""

    def __init__(self, cache: TileCache) -> None:
        self._cache: TileCache = cache

    def heuristic(self, x1: int, y1: int, x2: int, y2: int) -> int:
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        return (dx + dy) * COST_WATER

    def neighbors(self, node: PathNode) -> list[PathNode]:
        result: list[PathNode] = []

        for dx, dy in _DIRS:
            nx, ny = node.x + dx, node.y + dy
            tile = self._cache.get(nx, ny)
            if tile is None:
                continue

            cost = self._tile_cost(tile, node)
            if cost < 0:
                continue

            action = "move"
            if not tile.water and tile.buildable:
                action = "build_canal"

            result.append(PathNode(
                f_cost=0, g_cost=cost, x=nx, y=ny, action=action,
            ))

        return result

    def _tile_cost(self, tile: TileData, from_node: PathNode) -> int:
        # Existing water: very cheap
        if tile.water:
            from_tile = self._cache.get(from_node.x, from_node.y)
            # Height change between water bodies = lock needed
            if from_tile and from_tile.height != tile.height:
                return COST_LOCK
            return COST_WATER

        # Coast: transition
        if tile.coast:
            return COST_COAST

        # Buildable land: canal
        if tile.buildable:
            return COST_CANAL

        # Not buildable, not water: impassable
        return -1
