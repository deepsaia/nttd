"""Parquet writer for tile terrain data.

Stores the full tile grid once at session start and appends deltas
for terrain modifications.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.store import session_paths

logger = logging.getLogger(__name__)

# The bit layout get_map_terrain packs each tile into. Named here because this file is
# the only place that unpacks it, and a bare & 8 in the middle of a loop is unreadable.
_FLAG_WATER = 1
_FLAG_COAST = 2
_FLAG_BUILDABLE = 4
_FLAG_RAIL = 8
_FLAG_ROAD = 16
_FLAG_STATION = 32
_FLAG_TREE = 64
_FLAG_BRIDGE = 128
_FLAG_TUNNEL = 256

_SCHEMA = pa.schema([
    ("session_id", pa.string()),
    ("captured_at", pa.timestamp("us")),
    ("x", pa.int16()),
    ("y", pa.int16()),
    ("height", pa.int8()),
    ("slope", pa.int8()),
    # Kept as a bitmask because prepare_terrain_grid reads it directly, masking bit 0 for
    # water to build its height grid. The same three facts are also in the named columns
    # below; this one exists so the terrain map and the video keep working unchanged.
    # int16, not int8: the mask runs to 256 now that bridges and tunnels are in it, and
    # int8 tops out at 127.
    ("flags", pa.int16()),
    # What is ON the tile, and whose it is.
    #
    # The scan used to record height, slope and those three flags, which is enough to ask
    # whether ground is flat and dry and not enough to ask whether anything can be built
    # on it. A map without ownership or occupancy cannot answer "is this my track", "is
    # this tile taken" or "can I build here", which is most of what a route needs to know.
    ("owner", pa.int16()),
    ("has_rail", pa.bool_()),
    ("has_road", pa.bool_()),
    ("is_station", pa.bool_()),
    ("has_tree", pa.bool_()),
    # A crossing used to read as owned, unbuildable, and nothing else, which is
    # uninterpretable exactly where the interesting structure is.
    ("has_bridge", pa.bool_()),
    ("has_tunnel", pa.bool_()),
])


class TileWriter:
    """Writes tile terrain data to a Parquet file."""

    def __init__(self, session_id: str, data_dir: str | None = None) -> None:
        self.session_id = session_id
        root = Path(data_dir) if data_dir else session_paths.sessions_dir()
        self._file_path = root.resolve() / session_id / "tiles.parquet"

    def write_full_scan(self, rows_data: list[dict[str, Any]]) -> int:
        """Write the initial full tile scan from a ``get_map_terrain`` reply.

        Args:
            rows_data: ``{y, tiles: [[height, slope, flags, owner], ...]}`` per row. The
                owner is optional so a reply from an older GameScript still loads.

        Returns:
            Number of tiles written.
        """
        now = datetime.now(timezone.utc)
        records: list[dict[str, Any]] = []

        for row in rows_data:
            y = row.get("y")
            if y is None:
                continue
            for x, tile in enumerate(row.get("tiles") or [], start=1):
                flags = int(tile[2]) if len(tile) > 2 else 0
                records.append({
                    "session_id": self.session_id,
                    "captured_at": now,
                    "x": x,
                    "y": int(y),
                    "height": int(tile[0]),
                    "slope": int(tile[1]),
                    "flags": flags,
                    "owner": int(tile[3]) if len(tile) > 3 else -1,
                    # Unpacked into columns as well as kept as the mask, because a query
                    # reading this back should not have to know the bit layout.
                    "has_rail": bool(flags & _FLAG_RAIL),
                    "has_road": bool(flags & _FLAG_ROAD),
                    "is_station": bool(flags & _FLAG_STATION),
                    "has_tree": bool(flags & _FLAG_TREE),
                    "has_bridge": bool(flags & _FLAG_BRIDGE),
                    "has_tunnel": bool(flags & _FLAG_TUNNEL),
                })

        if not records:
            return 0

        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(records, schema=_SCHEMA)
        pq.write_table(table, self._file_path, compression="zstd")

        logger.info("Tile scan: %d tiles written to %s", len(records), self._file_path)
        return len(records)

    def write_delta(self, tiles: list[dict[str, Any]]) -> None:
        """Append a delta of changed tiles (after terrain modification actions).

        Args:
            tiles: List of {x, y, height, slope, flags} dicts.
        """
        if not tiles:
            return

        now = datetime.now(timezone.utc)
        records = [
            {
                "session_id": self.session_id,
                "captured_at": now,
                "x": int(t["x"]),
                "y": int(t["y"]),
                "height": int(t.get("height") or 0),
                "slope": int(t.get("slope") or 0),
                # A delta may arrive in either shape: a precomputed bitmask from an older
                # caller, or the named booleans get_tile_area returns. Concatenating onto
                # the scan needs identical columns either way.
                "flags": int(t["flags"]) if "flags" in t else _flags(t),
                "owner": int(t.get("owner", -1)),
                "has_rail": bool(t.get("has_rail")),
                "has_road": bool(t.get("has_road")),
                "is_station": bool(t.get("is_station")),
                "has_tree": bool(t.get("has_tree")),
                "has_bridge": bool(t.get("has_bridge")),
                "has_tunnel": bool(t.get("has_tunnel")),
            }
            for t in tiles
        ]

        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        new_table = pa.Table.from_pylist(records, schema=_SCHEMA)

        if self._file_path.exists():
            existing = pq.read_table(self._file_path, schema=_SCHEMA)
            new_table = pa.concat_tables([existing, new_table])

        pq.write_table(new_table, self._file_path, compression="zstd")
        logger.debug("Tile delta: %d tiles appended", len(records))

    @property
    def file_path(self) -> Path:
        return self._file_path


def _flags(tile: dict[str, Any]) -> int:
    """The terrain bitmask, from the named booleans.

    Kept alongside the booleans because prepare_terrain_grid masks bit 0 out of this
    column to decide which tiles are water, and the terrain map and the video both go
    through it.
    """
    flags = 0
    if tile.get("water"):
        flags |= _FLAG_WATER
    if tile.get("coast"):
        flags |= _FLAG_COAST
    if tile.get("buildable"):
        flags |= _FLAG_BUILDABLE
    return flags
