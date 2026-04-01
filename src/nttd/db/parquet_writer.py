"""Append-only Parquet writer for full snapshot replay data.

Snapshots are buffered in memory and flushed to a single Parquet file
per session. Parquet's built-in compression (zstd) replaces the old
gzip-in-SQLite approach with better compression and columnar access.

Ref: docs/openttd_study_part4_multiplayer_agent_design.md §13
"""

import json
import logging
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.schemas.snapshot import StateSnapshot

logger = logging.getLogger(__name__)

_FLUSH_THRESHOLD: int = 50

_SCHEMA = pa.schema([
    ("session_id", pa.string()),
    ("snapshot_id", pa.string()),
    ("game_date", pa.int32()),
    ("tick", pa.int32()),
    ("snapshot_json", pa.large_string()),
])


class ParquetWriter:
    """Buffers snapshots and writes them to a Parquet file."""

    def __init__(self, session_id: str, data_dir: str = "data/sessions") -> None:
        self.session_id: str = session_id
        self._data_dir: Path = Path(data_dir).resolve()
        self._file_path: Path = self._data_dir / session_id / "snapshots.parquet"
        self._buffer: list[dict[str, Any]] = []
        self._total_written: int = 0

    def append(self, snapshot: StateSnapshot) -> None:
        self._buffer.append({
            "session_id": self.session_id,
            "snapshot_id": snapshot.game.snapshot_id,
            "game_date": snapshot.game.game_date,
            "tick": snapshot.game.tick,
            "snapshot_json": json.dumps(snapshot.model_dump(), default=str),
        })
        if len(self._buffer) >= _FLUSH_THRESHOLD:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return

        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(self._buffer, schema=_SCHEMA)

        if self._file_path.exists():
            existing = pq.read_table(self._file_path, schema=_SCHEMA)
            table = pa.concat_tables([existing, table])

        pq.write_table(table, self._file_path, compression="zstd")

        self._total_written += len(self._buffer)
        logger.debug(
            "Parquet flush: %d snapshots written (%d total) to %s",
            len(self._buffer), self._total_written, self._file_path,
        )
        self._buffer.clear()

    @property
    def file_path(self) -> Path:
        return self._file_path

    @property
    def total_written(self) -> int:
        return self._total_written + len(self._buffer)
