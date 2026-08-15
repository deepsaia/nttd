"""The digest answers which world was played, so playing must not change it.

A tile scan is not one row per tile. The opening full scan is written once, then every
action appends the tiles it may have touched as a delta, so a played session carries the
same coordinate several times. The digest hashed every row, while the verifier regenerates
from the seed and digests a scan with each tile exactly once, so the two could never agree
and every developed session failed ``world_regenerated`` on a world that was identical.

Measured across the recorded sessions when this was found: 10 of 23 carried duplicates, up
to 9289 extra rows on a 64516 tile map. Two sessions on seed 1001, one of which built a
railway and levelled ground, now digest the same.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nttd.store.map_digest import map_digest

pytest.importorskip("pyarrow")


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(rows), path)


def _tile(x: int, y: int, stamp: int, **over: Any) -> dict[str, Any]:
    row = {"x": x, "y": y, "height": 2, "slope": 0, "flags": 4, "captured_at": stamp}
    row.update(over)
    return row


def test_a_delta_does_not_change_the_digest(tmp_path: Path) -> None:
    """The core of it: re-reading a tile after building on it must not restate the world."""
    scan = [_tile(x, y, 100) for x in range(1, 6) for y in range(1, 6)]
    scan_only = tmp_path / "scan.parquet"
    _write(scan_only, scan)

    # The same scan, plus one tile re-read after a station was built on it. flags gains
    # the station and buildable bits, which the digest masks away.
    played = tmp_path / "played.parquet"
    _write(played, [*scan, _tile(3, 3, 200, flags=4 | 32)])

    assert map_digest(played) == map_digest(scan_only)


def test_terraformed_ground_still_digests_as_the_world_that_was_generated(
    tmp_path: Path,
) -> None:
    """Height and slope are the ones that really move, and keeping the LATEST row would
    swap one mismatch for another on exactly the sessions that levelled anything."""
    scan = [_tile(x, y, 100) for x in range(1, 6) for y in range(1, 6)]
    scan_only = tmp_path / "scan.parquet"
    _write(scan_only, scan)

    levelled = tmp_path / "levelled.parquet"
    _write(levelled, [*scan, _tile(2, 4, 300, height=5, slope=2)])

    assert map_digest(levelled) == map_digest(scan_only)


def test_a_different_world_still_digests_differently(tmp_path: Path) -> None:
    """The check has to keep failing when it should. Deduping must not flatten everything
    to one value."""
    here = tmp_path / "here.parquet"
    _write(here, [_tile(x, y, 100) for x in range(1, 6) for y in range(1, 6)])

    elsewhere = tmp_path / "elsewhere.parquet"
    rows = [_tile(x, y, 100) for x in range(1, 6) for y in range(1, 6)]
    rows[7] = _tile(rows[7]["x"], rows[7]["y"], 100, height=9)
    _write(elsewhere, rows)

    assert map_digest(here) != map_digest(elsewhere)


def test_the_order_rows_were_written_in_does_not_matter(tmp_path: Path) -> None:
    """Deltas arrive in whatever order actions ran, and bands of the opening scan can be
    written out of order too."""
    rows = [_tile(x, y, 100) for x in range(1, 5) for y in range(1, 5)]
    forwards = tmp_path / "forwards.parquet"
    _write(forwards, rows)
    backwards = tmp_path / "backwards.parquet"
    _write(backwards, list(reversed(rows)))

    assert map_digest(forwards) == map_digest(backwards)
