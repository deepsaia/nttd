"""Append-only Parquet writer for full snapshot replay data.

Snapshots are buffered in memory and flushed to numbered fragment files.
On finalize(), fragments are merged into a single snapshots.parquet.

**``snapshot_json`` is the source. The typed columns are an index into it, never a
second record of it.** Every ``num_*`` and ``c0_*`` value is extracted from the same
snapshot on the way past, so where they disagree the JSON is right and the column is a
bug. Nothing may write one without the other, and nothing downstream may treat a typed
column as evidence the JSON does not already carry.

They are kept because a dashboard that filters or plots a series should not parse a
large JSON string per row to do it. Measured across three real sessions, ``c0_*`` plus
``num_*`` cost 5.4 to 6.4 percent of the file while ``snapshot_json`` is 59 to 75
percent, so the projection is cheap: removing it would save little and push JSON parsing
into every reader.

They are deliberately partial, and that is the reason they cannot become the record.
They cover company 0 only, and no expenses, so anything about another company or about
spend has to read the JSON regardless. ``analysis.business_metrics`` does exactly that.

Derived from the OpenTTD multiplayer/agent study, §13 (local research notes, not in the repo).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.schemas.snapshot import StateSnapshot
from nttd.store import session_paths

logger = logging.getLogger(__name__)

_FLUSH_THRESHOLD: int = 10

_SCHEMA = pa.schema([
    ("session_id", pa.string()),
    ("snapshot_id", pa.string()),
    ("game_date", pa.int32()),
    ("tick", pa.int32()),
    ("captured_at", pa.timestamp("us")),
    # The record. Everything below is extracted from this on the way past.
    ("snapshot_json", pa.large_string()),
    # --- Projection of snapshot_json, for querying without parsing it -------------
    # Top-level counts
    ("num_companies", pa.int16()),
    ("num_towns", pa.int16()),
    ("num_vehicles", pa.int16()),
    ("num_stations", pa.int16()),
    # Company 0 finance. Company 0 only, and no expenses: a projection wide enough for
    # a dashboard, deliberately not wide enough to be mistaken for the record.
    ("c0_balance", pa.int64()),
    ("c0_loan", pa.int64()),
    ("c0_income", pa.int64()),
    ("c0_value", pa.int64()),
    # Company 0 infrastructure piece counts and monthly maintenance costs
    ("c0_rail_pieces", pa.int32()),
    ("c0_road_pieces", pa.int32()),
    ("c0_water_pieces", pa.int32()),
    ("c0_station_pieces", pa.int32()),
    ("c0_airport_pieces", pa.int32()),
    ("c0_rail_cost", pa.int64()),
    ("c0_road_cost", pa.int64()),
    ("c0_water_cost", pa.int64()),
    ("c0_station_cost", pa.int64()),
    ("c0_airport_cost", pa.int64()),
])


class ParquetWriter:
    """Buffers snapshots and writes them to fragment files, merged on finalize."""

    def __init__(self, session_id: str, data_dir: str | None = None) -> None:
        self.session_id: str = session_id
        root = Path(data_dir) if data_dir else session_paths.sessions_dir()
        self._data_dir: Path = root.resolve()
        self._session_dir: Path = self._data_dir / session_id
        self._fragments_dir: Path = self._session_dir / "_fragments"
        self._file_path: Path = self._session_dir / "snapshots.parquet"
        self._buffer: list[dict[str, Any]] = []
        self._total_written: int = 0
        self._fragment_seq: int = 0

    def append(self, snapshot: StateSnapshot) -> None:
        c0 = next((c for c in snapshot.companies if c.id == 0), None)
        infra = next((i for i in snapshot.infrastructure if i.company_id == 0), None)
        self._buffer.append({
            "session_id": self.session_id,
            "snapshot_id": snapshot.game.snapshot_id,
            "game_date": snapshot.game.game_date,
            "tick": snapshot.game.tick,
            "captured_at": datetime.now(timezone.utc),
            "snapshot_json": json.dumps(snapshot.model_dump(), default=str),
            "num_companies": len(snapshot.companies),
            "num_towns": len(snapshot.towns),
            "num_vehicles": len(snapshot.vehicles),
            "num_stations": len(snapshot.stations),
            "c0_balance": c0.money if c0 else 0,
            "c0_loan": c0.loan if c0 else 0,
            "c0_income": c0.income if c0 else 0,
            "c0_value": c0.value if c0 else 0,
            "c0_rail_pieces": infra.rail_pieces if infra else 0,
            "c0_road_pieces": infra.road_pieces if infra else 0,
            "c0_water_pieces": infra.water_pieces if infra else 0,
            "c0_station_pieces": infra.station_pieces if infra else 0,
            "c0_airport_pieces": infra.airport_pieces if infra else 0,
            "c0_rail_cost": infra.rail_cost if infra else 0,
            "c0_road_cost": infra.road_cost if infra else 0,
            "c0_water_cost": infra.water_cost if infra else 0,
            "c0_station_cost": infra.station_cost if infra else 0,
            "c0_airport_cost": infra.airport_cost if infra else 0,
        })
        if len(self._buffer) >= _FLUSH_THRESHOLD:
            self.flush()

    def flush(self) -> None:
        """Write buffered snapshots to a new fragment file."""
        if not self._buffer:
            return

        self._fragments_dir.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(self._buffer, schema=_SCHEMA)

        fragment_path = self._fragments_dir / f"snapshots_{self._fragment_seq:04d}.parquet"
        self._fragment_seq += 1
        pq.write_table(table, fragment_path, compression="zstd")

        self._total_written += len(self._buffer)
        logger.debug(
            "Snapshot fragment: %d snapshots written (%d total) to %s",
            len(self._buffer), self._total_written, fragment_path.name,
        )
        self._buffer.clear()

    def finalize(self) -> None:
        """Merge all snapshot fragments into a single snapshots.parquet."""
        self.flush()  # flush any remaining buffer

        fragments = sorted(self._fragments_dir.glob("snapshots_*.parquet"))
        if not fragments:
            return

        tables: list[pa.Table] = []
        for frag_path in fragments:
            try:
                tables.append(pq.read_table(frag_path, schema=_SCHEMA))
            except Exception:
                logger.warning("Failed to read snapshot fragment %s, skipping", frag_path.name)

        if tables:
            merged = pa.concat_tables(tables)
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(merged, self._file_path, compression="zstd")
            logger.info(
                "Merged %d snapshot fragments (%d rows) into %s",
                len(fragments), merged.num_rows, self._file_path.name,
            )

        # Clean up fragments
        for frag_path in fragments:
            frag_path.unlink(missing_ok=True)

    @property
    def file_path(self) -> Path:
        return self._file_path

    @property
    def total_written(self) -> int:
        return self._total_written + len(self._buffer)
