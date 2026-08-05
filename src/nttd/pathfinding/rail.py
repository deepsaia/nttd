"""Rail pathfinder — direction-aware A* on rail-buildable tiles.

Tracks direction because trains can't make arbitrary turns.
Cost model: flat=100, slope=+200, curve45=100, curve90=600, bridge/tunnel.
Bridge/tunnel neighbor expansion with max length limits.

Derived from the OpenTTD multiplayer/agent study, §14.4 (local research notes, not in the repo).
"""

from nttd.pathfinding.astar import PathNode
from nttd.pathfinding.tile_cache import TileCache, TileData

COST_FLAT: int = 100
COST_SLOPE: int = 200
COST_CURVE_45: int = 100
COST_CURVE_90: int = 600
COST_CROSSING: int = 300
COST_DEMOLISH: int = 500
COST_BRIDGE_PER_TILE: int = 150
COST_TUNNEL_PER_TILE: int = 120

MAX_BRIDGE_LENGTH: int = 6
MAX_TUNNEL_LENGTH: int = 6

# Direction: 0=N, 1=E, 2=S, 3=W
_DIR_DELTAS: list[tuple[int, int]] = [(0, -1), (1, 0), (0, 1), (-1, 0)]


class RailCostFunction:
    """Direction-aware cost function for rail pathfinding with bridge/tunnel support."""

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
        d_min = min(dx, dy)
        d_max = max(dx, dy)
        return d_min * 71 + (d_max - d_min) * COST_FLAT

    def neighbors(self, node: PathNode) -> list[PathNode]:
        result: list[PathNode] = []
        entry_dir = node.direction

        for new_dir in range(4):
            # Can't reverse (180 degree turn)
            if entry_dir >= 0 and (new_dir + 2) % 4 == entry_dir:
                continue

            dx, dy = _DIR_DELTAS[new_dir]
            nx, ny = node.x + dx, node.y + dy
            tile = self._cache.get(nx, ny)
            if tile is None:
                continue

            cost = self._tile_cost(tile, entry_dir, new_dir, nx, ny)
            if cost >= 0:
                result.append(PathNode(
                    f_cost=0, g_cost=cost, x=nx, y=ny,
                    direction=new_dir,
                    action="build_rail" if not tile.has_rail else "move",
                ))
            else:
                # Tile impassable — try bridge/tunnel in the same direction
                # Only attempt if continuing straight (no turn into bridge)
                if entry_dir < 0 or new_dir == entry_dir:
                    bridge = self._try_bridge(node.x, node.y, new_dir)
                    if bridge is not None:
                        result.append(bridge)

                    tunnel = self._try_tunnel(node.x, node.y, new_dir)
                    if tunnel is not None:
                        result.append(tunnel)

        return result

    def _try_bridge(self, sx: int, sy: int, direction: int) -> PathNode | None:
        """Scan forward for a valid rail bridge endpoint."""
        dx, dy = _DIR_DELTAS[direction]
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

            if end_tile.water or end_tile.is_station:
                continue
            if not end_tile.buildable and not end_tile.has_rail:
                continue

            if end_tile.height == start_height:
                cost = length * COST_BRIDGE_PER_TILE
                return PathNode(
                    f_cost=0, g_cost=cost, x=bx, y=by,
                    direction=direction,
                    action="build_bridge",
                    meta={"bridge_from_x": sx, "bridge_from_y": sy, "length": length},
                )

        return None

    def _try_tunnel(self, sx: int, sy: int, direction: int) -> PathNode | None:
        """Scan forward for a valid rail tunnel exit."""
        dx, dy = _DIR_DELTAS[direction]
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

            if end_tile.height < start_height:
                break

            if end_tile.height == start_height and end_tile.slope != 0:
                cost = length * COST_TUNNEL_PER_TILE
                return PathNode(
                    f_cost=0, g_cost=cost, x=tx, y=ty,
                    direction=direction,
                    action="build_tunnel",
                    meta={"tunnel_from_x": sx, "tunnel_from_y": sy, "length": length},
                )

        return None

    def _tile_cost(
        self, tile: TileData, entry_dir: int, new_dir: int,
        nx: int, ny: int,
    ) -> int:
        if tile.is_station or tile.water:
            return -1

        cost = COST_FLAT

        # Slope penalty
        if tile.slope != 0:
            cost += COST_SLOPE

        # Turn penalty
        if entry_dir >= 0:
            turn = abs(new_dir - entry_dir) % 4
            if turn == 0:
                pass
            elif turn == 1 or turn == 3:
                cost += COST_CURVE_45
            elif turn == 2:
                return -1  # 180 blocked above, but safety

        # Existing rail — check ownership
        if tile.has_rail:
            if tile.owner >= 0 and tile.owner != self._company_id:
                return -1
            return cost // 2

        # Road crossing
        if tile.has_road:
            cost += COST_CROSSING

        # Not buildable
        if not tile.buildable and not tile.has_rail:
            if self._avoid_demolish:
                return -1
            cost += COST_DEMOLISH

        return cost
