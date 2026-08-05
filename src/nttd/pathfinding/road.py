"""Road pathfinder — A* on road-buildable tiles.

Cost model aligned with YAPF and AI Pathfinder.Road v3:
  flat=100, slope=+200, bridge=150/tile, tunnel=120/tile, demolish=500
  Bridge/tunnel neighbor expansion with max length limits.

Derived from the OpenTTD multiplayer/agent study, §14.4 (local research notes, not in the repo).
"""

from nttd.pathfinding.astar import PathNode
from nttd.pathfinding.tile_cache import TileCache, TileData

COST_FLAT: int = 100
COST_SLOPE: int = 200
COST_BRIDGE_PER_TILE: int = 150
COST_TUNNEL_PER_TILE: int = 120
COST_DEMOLISH: int = 500
COST_CROSSING: int = 300

MAX_BRIDGE_LENGTH: int = 10
MAX_TUNNEL_LENGTH: int = 20

# 4-directional movement (NESW): index = direction
_DIRS: list[tuple[int, int]] = [(0, -1), (1, 0), (0, 1), (-1, 0)]


class RoadCostFunction:
    """Cost function for road pathfinding with bridge/tunnel support."""

    def __init__(
        self, cache: TileCache, avoid_demolish: bool = False,
        company_id: int = -1,
    ) -> None:
        self._cache: TileCache = cache
        self._avoid_demolish: bool = avoid_demolish
        self._company_id: int = company_id

    def heuristic(self, x1: int, y1: int, x2: int, y2: int) -> int:
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        return (dx + dy) * COST_FLAT

    def neighbors(self, node: PathNode) -> list[PathNode]:
        result: list[PathNode] = []

        for direction, (dx, dy) in enumerate(_DIRS):
            nx, ny = node.x + dx, node.y + dy
            tile = self._cache.get(nx, ny)
            if tile is None:
                continue

            # Normal tile movement
            cost = self._tile_cost(tile, node, nx, ny)
            if cost >= 0:
                result.append(PathNode(
                    f_cost=0, g_cost=cost, x=nx, y=ny,
                    action="build_road" if not tile.has_road else "move",
                ))
            else:
                # Tile is impassable — try bridge or tunnel
                bridge = self._try_bridge(node.x, node.y, direction)
                if bridge is not None:
                    result.append(bridge)

                tunnel = self._try_tunnel(node.x, node.y, direction)
                if tunnel is not None:
                    result.append(tunnel)

        return result

    def _try_bridge(self, sx: int, sy: int, direction: int) -> PathNode | None:
        """Scan forward for a valid bridge endpoint (land tile after water/valley)."""
        dx, dy = _DIRS[direction]
        start_tile = self._cache.get(sx, sy)
        if start_tile is None:
            return None
        start_height = start_tile.height

        for length in range(2, MAX_BRIDGE_LENGTH + 1):
            bx = sx + dx * length
            by = sy + dy * length
            end_tile = self._cache.get(bx, by)
            if end_tile is None:
                break

            # Bridge endpoint must be buildable land at same or similar height
            if end_tile.water or end_tile.is_station:
                continue
            if not end_tile.buildable and not end_tile.has_road:
                continue

            # Valid bridge: height matches and intermediate tiles are crossable
            if end_tile.height == start_height:
                cost = length * COST_BRIDGE_PER_TILE
                return PathNode(
                    f_cost=0, g_cost=cost, x=bx, y=by,
                    action="build_bridge",
                    meta={"bridge_from_x": sx, "bridge_from_y": sy, "length": length},
                )

        return None

    def _try_tunnel(self, sx: int, sy: int, direction: int) -> PathNode | None:
        """Scan forward for a valid tunnel exit (same height through elevated terrain)."""
        dx, dy = _DIRS[direction]
        start_tile = self._cache.get(sx, sy)
        if start_tile is None or start_tile.slope == 0:
            return None
        start_height = start_tile.height

        for length in range(2, MAX_TUNNEL_LENGTH + 1):
            tx = sx + dx * length
            ty = sy + dy * length
            end_tile = self._cache.get(tx, ty)
            if end_tile is None:
                break

            # Tunnel must go through higher terrain
            if end_tile.height < start_height:
                break

            # Tunnel exit: same height, has slope (matching exit)
            if end_tile.height == start_height and end_tile.slope != 0:
                cost = length * COST_TUNNEL_PER_TILE
                return PathNode(
                    f_cost=0, g_cost=cost, x=tx, y=ty,
                    action="build_tunnel",
                    meta={"tunnel_from_x": sx, "tunnel_from_y": sy, "length": length},
                )

        return None

    def _tile_cost(
        self, tile: TileData, from_node: PathNode, nx: int, ny: int,
    ) -> int:
        # Can't build on station/water (unless bridge)
        if tile.is_station:
            return -1
        if tile.water and not tile.coast:
            return -1

        cost = COST_FLAT

        # Slope penalty
        if tile.slope != 0:
            cost += COST_SLOPE

        # Already has road — free to use if ours or unowned
        if tile.has_road:
            if tile.owner >= 0 and tile.owner != self._company_id:
                return -1
            return cost // 2

        # Has rail — crossing penalty
        if tile.has_rail:
            cost += COST_CROSSING

        # Not buildable — demolish needed
        if not tile.buildable and not tile.has_road:
            if self._avoid_demolish:
                return -1
            cost += COST_DEMOLISH

        return cost
