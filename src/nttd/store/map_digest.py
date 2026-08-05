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

logger = logging.getLogger(__name__)

# The terrain columns, in the order they are fed to the hash. Anything about *when* or
# *by whom* the scan was taken is excluded on purpose.
TERRAIN_COLUMNS = ("x", "y", "height", "slope", "flags")

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

        table = pq.read_table(path, columns=list(TERRAIN_COLUMNS))
    except Exception:
        logger.exception("Could not read a tile scan from %s", path)
        return None

    if table.num_rows == 0:
        return None

    columns = [table.column(name).to_pylist() for name in TERRAIN_COLUMNS]
    rows = sorted(zip(*columns, strict=True))

    digest = hashlib.sha256()
    for row in rows:
        digest.update((",".join(str(value) for value in row) + "\n").encode())
    return digest.hexdigest()[:_DIGEST_LENGTH]
