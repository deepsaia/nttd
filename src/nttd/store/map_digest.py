"""A reproducible digest of the world a session was played on.

Step 1 of verification regenerates the world from the declared seed and settings and
checks it is the world that was played. That needs a digest two independent generations
of the same seed both arrive at, which rules out hashing `tiles.parquet` itself: the
file carries a `session_id` and a `captured_at` timestamp, and Parquet encoding is free
to differ between writers. Hashing the bytes would report every run as a different
world.

So this hashes the terrain only, in a fixed order: `(x, y, height, slope, flags)` sorted
by position. That is the part of the file the seed actually determines.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The terrain columns, in the order they are fed to the hash. Anything about *when* or
# *by whom* the scan was taken is excluded on purpose.
TERRAIN_COLUMNS = ("x", "y", "height", "slope", "flags")

# Only the bits of `flags` that describe the GENERATED world.
#
# The digest exists to prove which world was played, so it must depend on the seed and on
# nothing else. The flags column also carries what is BUILT on a tile: rail, road, station,
# tree, bridge, tunnel, and a buildable bit that goes false as soon as anything is put
# there. Hashing those would make a world's identity depend on how the company played it.
# The same map would then digest differently before and after a station went up, and the
# verifier, which regenerates an EMPTY world from the seed, would report every developed
# run as a different world.
#
# Water and coast are terrain, so they are hashed. Height and slope are terrain outright.
_TERRAIN_BITS = 1 | 2

_DIGEST_LENGTH = 16


def map_digest(tiles_path: Path | str) -> str | None:
    """Return a digest of the terrain in a tile scan, or None if it cannot be read.

    None rather than an exception: a session recorded without a tile scan should still
    produce a bundle, with the absence visible as a verification gap.
    """
    path = Path(tiles_path)
    if not path.exists():
        return None

    try:
        import pyarrow.parquet as pq

        table = pq.read_table(path, columns=[*TERRAIN_COLUMNS, "captured_at"])
    except Exception:
        logger.exception("Could not read a tile scan from %s", path)
        return None

    if table.num_rows == 0:
        return None

    columns = [table.column(name).to_pylist() for name in TERRAIN_COLUMNS]
    flags_at = TERRAIN_COLUMNS.index("flags")
    columns[flags_at] = [int(value or 0) & _TERRAIN_BITS for value in columns[flags_at]]
    rows = _one_row_per_tile(columns, table.column("captured_at").to_pylist())

    digest = hashlib.sha256()
    for row in rows:
        digest.update((",".join(str(value) for value in row) + "\n").encode())
    return digest.hexdigest()[:_DIGEST_LENGTH]


def _one_row_per_tile(
    columns: list[list[Any]], captured_at: list[Any],
) -> list[tuple[Any, ...]]:
    """The world as generated: the EARLIEST row recorded for each tile, sorted.

    A tile scan is not one row per tile. The opening full scan is written once, and every
    action then appends the tiles it may have touched as a delta, so a played session
    carries the same coordinate several times. Measured across the recorded sessions: 10 of
    23 have duplicates, up to 9289 extra rows on a 64516 tile map.

    The digest exists to answer one question, which world was played, and the verifier
    answers it by regenerating from the seed and digesting a scan with each tile exactly
    once. Hashing every row could therefore never agree, and every developed session failed
    ``world_regenerated`` on a world that was in fact identical.

    Earliest rather than latest, deliberately. Terraforming changes a tile's height and
    slope, so the last row records what the contestant made of the ground while only the
    first records what the seed produced. Keeping the latest would swap one mismatch for
    another on exactly the sessions that levelled anything.
    """
    earliest: dict[tuple[Any, Any], tuple[Any, tuple[Any, ...]]] = {}
    for index, stamp in enumerate(captured_at):
        row = tuple(column[index] for column in columns)
        key = (row[0], row[1])
        seen = earliest.get(key)
        if seen is None or stamp < seen[0]:
            earliest[key] = (stamp, row)
    return sorted(row for _, row in earliest.values())
