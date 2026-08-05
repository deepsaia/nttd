"""The single read path for a session's Parquet files.

Reads the merged file when it exists and falls back to the per-write fragments a
running session leaves under `_fragments/`, so a query against a live session sees
the rows a query after it ended would see. The five repositories each opened
Parquet themselves and none of them handled fragments, so every API read against a
running session silently omitted everything not yet merged.

Returns pyarrow rather than polars because that is what both consumers can use: the
API turns rows into JSON, and the analysis loader wraps the same table in polars.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.db import session_paths

logger = logging.getLogger(__name__)

SNAPSHOTS = "snapshots"


def read_table(
    session_id: str,
    name: str,
    columns: list[str] | None = None,
    sessions_dir: Path | str | None = None,
) -> pa.Table | None:
    """Read one Parquet type for a session, or None if it has recorded nothing.

    `name` is the file stem: "actions", "events", "snapshots", "tiles", "result".
    `sessions_dir` addresses a root other than the configured one, which tests need
    and nothing in the server does.
    """
    root = Path(sessions_dir) if sessions_dir is not None else session_paths.sessions_dir()
    session_dir = root / session_id

    merged = session_dir / f"{name}.parquet"
    if merged.exists():
        try:
            return pq.read_table(merged, columns=columns)
        except Exception:
            logger.warning("Failed to read %s, trying fragments", merged)

    return read_fragments(session_dir, name, columns)


def read_rows(
    session_id: str,
    name: str,
    columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read one Parquet type for a session as a list of dicts."""
    table = read_table(session_id, name, columns)
    if table is None:
        return []
    return table.to_pylist()


def read_snapshot_columns(
    session_id: str,
    columns: list[str],
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Read snapshot rows as dicts of game_date plus `columns`, filtered by date.

    Every caller wants game_date, so it is always included and need not be listed.
    """
    wanted = ["game_date", *[c for c in columns if c != "game_date"]]
    rows = read_rows(session_id, SNAPSHOTS, wanted)
    return [r for r in rows if _in_range(r.get("game_date"), from_date, to_date)]


def read_snapshots(
    session_id: str,
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    """Read parsed snapshots as (game_date, snapshot) pairs, filtered by date.

    Parses every snapshot in the range, so narrow the range when you can. Use
    latest_snapshot, first_snapshot or snapshot_at to reach a single point in time:
    each parses one row instead of the whole series.
    """
    pairs: list[tuple[int, dict[str, Any]]] = []
    for row in read_snapshot_columns(session_id, ["snapshot_json"], from_date, to_date):
        snapshot = _parse(row, session_id)
        if snapshot is not None:
            pairs.append((row["game_date"], snapshot))
    return pairs


def latest_snapshot(session_id: str) -> dict[str, Any] | None:
    """Return the snapshot with the highest game_date, or None if there are none."""
    rows = read_snapshot_columns(session_id, ["snapshot_json"])
    if not rows:
        return None
    return _parse(max(rows, key=lambda row: row["game_date"]), session_id)


def first_snapshot(session_id: str) -> dict[str, Any] | None:
    """Return the snapshot with the lowest game_date, or None if there are none."""
    rows = read_snapshot_columns(session_id, ["snapshot_json"])
    if not rows:
        return None
    return _parse(min(rows, key=lambda row: row["game_date"]), session_id)


def snapshot_at(session_id: str, game_date: int) -> dict[str, Any] | None:
    """Return the snapshot at game_date, or the closest one if there is no exact match.

    Snapshots are written on an interval, so an arbitrary date usually falls between
    two of them. Answering with the nearest is more useful than answering with
    nothing, since the caller asked about a point on a continuous timeline.
    """
    rows = read_snapshot_columns(session_id, ["snapshot_json"])
    if not rows:
        return None
    return _parse(min(rows, key=lambda row: abs(row["game_date"] - game_date)), session_id)


def _parse(row: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    """Parse one snapshot row's JSON, or None if it is absent or unreadable.

    A snapshot that fails to parse is skipped with a warning rather than failing the
    whole query: one bad row should not hide an otherwise readable session.
    """
    raw = row.get("snapshot_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Unparseable snapshot at game_date %s in session %s, skipping",
            row.get("game_date"), session_id,
        )
        return None


def _in_range(value: int | None, from_date: int | None, to_date: int | None) -> bool:
    """Return whether a game_date falls inside an optional inclusive range."""
    if value is None:
        return False
    if from_date is not None and value < from_date:
        return False
    return not (to_date is not None and value > to_date)


def read_fragments(
    session_dir: Path,
    name: str,
    columns: list[str] | None = None,
) -> pa.Table | None:
    """Concatenate the fragment files a running session has not yet merged."""
    fragments_dir = session_dir / "_fragments"
    if not fragments_dir.exists():
        return None

    tables: list[pa.Table] = []
    for path in sorted(fragments_dir.glob(f"{name}_*.parquet")):
        try:
            tables.append(pq.read_table(path, columns=columns))
        except Exception:
            logger.warning("Failed to read fragment %s, skipping", path)

    if not tables:
        return None
    return pa.concat_tables(tables, promote_options="permissive")
