"""Reading a whole map's terrain, one bounded band at a time.

Shared because there are two callers and they must agree: a session captures its map at
startup, and the verifier regenerates the world from the seed and captures it again to
compare digests. If those two read the map differently, the comparison is meaningless
however carefully it is computed.

They did read it differently. ``get_map_terrain`` was bounded and its reply changed from a
list of rows to a table wrapping them. The session capture was updated and the verifier was
not, so it kept asking for one unbounded band and reading the reply as a list. It got a
table, wrote nothing, and reported that every submission had regenerated to an empty world.

The same shape of bug had already happened twice elsewhere in this codebase, both times a
second caller carrying its own copy of a rule. Hence one function.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Tiles per band. The handler's own ceiling is 20,000, and asking for it means the fewest
# round trips: a 256 square map is four bands rather than seventeen at the default. Replies
# are chunked to fit the admin packet limit, so a large band costs packets rather than
# risking the connection.
SCAN_BAND = 20000


class Query(Protocol):
    """Whatever can ask the GameScript a question and wait for the answer."""

    async def __call__(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        ...


async def scan_terrain(query: Query) -> list[dict[str, Any]] | None:
    """Every terrain row of the map, or None if any band failed.

    None rather than a partial list on failure: a half scanned map that looks complete is
    worse than no scan, because it silently becomes a smaller world in anything that reads
    it, including a digest that is supposed to prove which world was played.
    """
    rows: list[dict[str, Any]] = []
    from_y = 1
    while True:
        reply = await query(
            "get_map_terrain", {"from_y": from_y, "max_tiles": SCAN_BAND},
        )
        band = reply.get("result")
        if not reply.get("success") or not isinstance(band, dict):
            logger.warning(
                "Terrain scan failed at row %d: %s", from_y, reply.get("error", "unknown"),
            )
            return None
        rows.extend(band.get("rows") or [])
        if not band.get("truncated"):
            return rows
        next_from_y = band.get("next_from_y")
        if not isinstance(next_from_y, int) or next_from_y <= from_y:
            # Without this the loop would ask for the same band forever. A handler that
            # says it truncated but cannot say where to resume is a bug there, not a
            # reason to spin here.
            logger.warning("Terrain scan stopped at row %d: no usable next_from_y", from_y)
            return rows
        from_y = next_from_y
