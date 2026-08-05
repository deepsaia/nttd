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

_SCHEMA = pa.schema([
    ("session_id", pa.string()),
    ("captured_at", pa.timestamp("us")),
    ("x", pa.int16()),
    ("y", pa.int16()),
    ("height", pa.int8()),
    ("slope", pa.int8()),
    ("flags", pa.int8()),
])


class TileWriter:
    """Writes tile terrain data to a Parquet file."""

    def __init__(self, session_id: str, data_dir: str | None = None) -> None:
        self.session_id = session_id
        root = Path(data_dir) if data_dir else session_paths.sessions_dir()
        self._file_path = root.resolve() / session_id / "tiles.parquet"

    def write_full_scan(self, rows_data: list[dict[str, Any]]) -> int:
        """Write the initial full tile scan from GS get_map_terrain response.

        Args:
            rows_data: List of {y, tiles: [[height, slope, flags], ...]} dicts
                as returned by the GS command.

        Returns:
            Number of tiles written.
        """
        now = datetime.now(timezone.utc)
        records: list[dict[str, Any]] = []

        for row in rows_data:
            y = row["y"]
            for x, tile_data in enumerate(row["tiles"], start=1):
                records.append({
                    "session_id": self.session_id,
                    "captured_at": now,
                    "x": x,
                    "y": y,
                    "height": tile_data[0],
                    "slope": tile_data[1],
                    "flags": tile_data[2],
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
                "x": t["x"],
                "y": t["y"],
                "height": t["height"],
                "slope": t["slope"],
                "flags": t["flags"],
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
