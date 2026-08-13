"""In-memory tile cache for pathfinding.

Loads tile data from GS via batched get_tile_area commands.
Invalidated when construction commands modify the map.

Derived from the OpenTTD multiplayer/agent study, §14.3 (local research notes, not in the repo).
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

BATCH_SIZE: int = 20


@dataclass(slots=True)
class TileData:
    height: int = 0
    slope: int = 0
    buildable: bool = False
    water: bool = False
    coast: bool = False
    has_road: bool = False
    has_rail: bool = False
    owner: int = -1
    is_station: bool = False
    has_tree: bool = False


class TileCache:
    """2D tile array loaded from GS for pathfinding."""

    def __init__(self, map_width: int, map_height: int) -> None:
        self.map_width: int = map_width
        self.map_height: int = map_height
        self._tiles: list[list[TileData | None]] = [
            [None] * map_height for _ in range(map_width)
        ]
        self._loaded: bool = False
        self._version: int = 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def version(self) -> int:
        return self._version

    def get(self, x: int, y: int) -> TileData | None:
        if 0 <= x < self.map_width and 0 <= y < self.map_height:
            return self._tiles[x][y]
        return None

    def set_tile(self, x: int, y: int, data: TileData) -> None:
        if 0 <= x < self.map_width and 0 <= y < self.map_height:
            self._tiles[x][y] = data

    async def load_area(
        self, gs_client: Any, x1: int, y1: int, x2: int, y2: int,
    ) -> int:
        """Load a rectangular area from GS. Returns number of tiles loaded."""
        # Inclusive throughout, matching get_tile_area. range() stops one short, so the
        # loops run to x2 and y2 and each batch ends on a real tile rather than one past
        # it. Read the other way, this missed the last row and column of every area it
        # loaded, which for a corridor is precisely the edge a route runs along.
        count = 0
        for bx in range(x1, x2 + 1, BATCH_SIZE):
            for by in range(y1, y2 + 1, BATCH_SIZE):
                ex = min(bx + BATCH_SIZE - 1, x2)
                ey = min(by + BATCH_SIZE - 1, y2)
                result = await gs_client.send_gamescript(
                    "get_tile_area",
                    {"x1": bx, "y1": by, "x2": ex, "y2": ey},
                    timeout=15.0,
                )
                if result.get("success") and isinstance(result.get("result"), list):
                    for td in result["result"]:
                        self._apply_tile(td)
                        count += 1
        self._version += 1
        return count

    async def load_full(self, gs_client: Any) -> int:
        """Load entire map. Use for small maps only."""
        count = await self.load_area(
            gs_client, 1, 1, self.map_width - 1, self.map_height - 1,
        )
        self._loaded = True
        logger.info("TileCache loaded %d tiles (%dx%d)", count, self.map_width, self.map_height)
        return count

    async def load_corridor(
        self, gs_client: Any, x1: int, y1: int, x2: int, y2: int, margin: int = 5,
    ) -> int:
        """Load a corridor between two points with margin for pathfinding."""
        lx = max(1, min(x1, x2) - margin)
        ly = max(1, min(y1, y2) - margin)
        hx = min(self.map_width - 1, max(x1, x2) + margin)
        hy = min(self.map_height - 1, max(y1, y2) + margin)
        return await self.load_area(gs_client, lx, ly, hx, hy)

    def invalidate_area(self, x1: int, y1: int, x2: int, y2: int) -> None:
        for x in range(max(0, x1), min(self.map_width, x2)):
            for y in range(max(0, y1), min(self.map_height, y2)):
                self._tiles[x][y] = None
        self._version += 1

    def invalidate_tile(self, x: int, y: int) -> None:
        if 0 <= x < self.map_width and 0 <= y < self.map_height:
            self._tiles[x][y] = None
            self._version += 1

    def _apply_tile(self, data: dict[str, Any]) -> None:
        x = data.get("x", -1)
        y = data.get("y", -1)
        if 0 <= x < self.map_width and 0 <= y < self.map_height:
            self._tiles[x][y] = TileData(
                height=data.get("height", 0),
                slope=data.get("slope", 0),
                buildable=data.get("buildable", False),
                water=data.get("water", False),
                coast=data.get("coast", False),
                has_road=data.get("has_road", False),
                has_rail=data.get("has_rail", False),
                owner=data.get("owner", -1),
                is_station=data.get("is_station", False),
                has_tree=data.get("has_tree", False),
            )
