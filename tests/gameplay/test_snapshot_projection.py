"""The typed snapshot columns are a projection of ``snapshot_json``, never a rival to it.

``snapshots.parquet`` holds the whole snapshot as JSON and, beside it, a handful of typed
columns extracted from that same snapshot. Two records of one fact is the shape this
project keeps removing: `final_snapshot.parquet` and `trajectory.parquet` were deleted for
it, and `manifest.json` is documented as a projection of `result.parquet` for the same
reason.

These columns stay, because the trade is different. Measured across three real sessions
they cost 5.4 to 6.4 percent of the file while ``snapshot_json`` is 59 to 75 percent, and
without them a dashboard parses a large JSON string per row to plot a balance. What makes
them safe is that they are derived on the way past and never written independently, which
is what these tests hold.

They are also deliberately partial: company 0 only, and no expenses. Anything wider has to
read the JSON. That is the property that stops the
projection quietly becoming the record.
"""

from __future__ import annotations

import json

import pytest

from nttd.schemas.snapshot import StateSnapshot
from nttd.store.parquet_writer import _SCHEMA, ParquetWriter

PROJECTED = tuple(
    name for name in _SCHEMA.names if name.startswith(("c0_", "num_"))
)


def _snapshot() -> StateSnapshot:
    """A snapshot with company 0 and a rival, so a projection that ignored the id shows."""
    return StateSnapshot.model_validate({
        "game": {"game_date": 733042, "tick": 512, "snapshot_id": "snap-1"},
        "companies": [
            {"id": 0, "name": "ours", "money": 412_000, "loan": 90_000,
             "income": 51_500, "value": 733_000},
            {"id": 1, "name": "theirs", "money": 9_000_000, "loan": 0,
             "income": 4_000_000, "value": 12_000_000},
        ],
        "infrastructure": [
            {"company_id": 0, "rail_pieces": 41, "road_pieces": 12, "water_pieces": 3,
             "station_pieces": 7, "airport_pieces": 1, "rail_cost": 820,
             "road_cost": 240, "water_cost": 60, "station_cost": 140,
             "airport_cost": 900},
            {"company_id": 1, "rail_pieces": 999, "road_pieces": 999,
             "water_pieces": 999, "station_pieces": 999, "airport_pieces": 999,
             "rail_cost": 999, "road_cost": 999, "water_cost": 999,
             "station_cost": 999, "airport_cost": 999},
        ],
        "towns": [{"id": 0, "name": "a"}, {"id": 1, "name": "b"}],
        "vehicles": [{"id": 0}, {"id": 1}, {"id": 2}],
        "stations": [{"id": 0}],
    })


@pytest.fixture
def row(tmp_path) -> dict:
    writer = ParquetWriter("ses_projection", data_dir=str(tmp_path))
    writer.append(_snapshot())
    return writer._buffer[0]


class TestEveryProjectedColumnComesFromTheJson:
    def test_the_json_is_the_whole_snapshot(self, row: dict) -> None:
        recorded = json.loads(row["snapshot_json"])
        assert len(recorded["companies"]) == 2
        assert len(recorded["infrastructure"]) == 2

    @pytest.mark.parametrize("column", PROJECTED)
    def test_it_agrees_with_the_json(self, row: dict, column: str) -> None:
        """Recomputed from the JSON in the same row rather than compared with the
        fixture, so this asserts the two agree rather than that both match what I typed."""
        recorded = json.loads(row["snapshot_json"])
        companies = {c["id"]: c for c in recorded["companies"]}
        infra = {i["company_id"]: i for i in recorded["infrastructure"]}

        counts = {
            "num_companies": len(recorded["companies"]),
            "num_towns": len(recorded["towns"]),
            "num_vehicles": len(recorded["vehicles"]),
            "num_stations": len(recorded["stations"]),
        }
        if column in counts:
            assert row[column] == counts[column]
            return

        # c0_balance is the one column whose name differs from its source field: the
        # snapshot calls it `money`. Spelled out rather than derived, so the rename is
        # visible instead of being hidden behind a lookup that happens to find it.
        field = {"balance": "money"}.get(
            column.removeprefix("c0_"), column.removeprefix("c0_"),
        )
        source = companies[0] if field in companies[0] else infra[0]
        assert field in source, f"{column} projects nothing in the snapshot"
        assert row[column] == source[field]

    def test_it_reads_company_zero_and_not_the_first_row(self, row: dict) -> None:
        """Company 1 is richer in the fixture on every field. A projection that took
        whichever company came first, or the maximum, would pass the agreement test
        above only by accident."""
        assert row["c0_balance"] == 412_000
        assert row["c0_rail_pieces"] == 41

    def test_the_schema_has_no_projected_column_this_test_misses(self) -> None:
        """Derived from the schema rather than listed, so a column added later is
        covered without anybody remembering to add it here."""
        assert len(PROJECTED) == 18  # 4 counts, 14 for company 0


class TestTheProjectionStaysPartial:
    def test_it_covers_no_company_but_zero(self) -> None:
        """A c1_ column would make the projection a second record of the snapshot, and
        the reason to keep it cheap would be gone."""
        assert not [n for n in _SCHEMA.names if n.startswith("c1_")]

    def test_it_carries_no_expenses(self) -> None:
        """Anything wanting expenses reads snapshot_json, precisely because they are absent here.
        Adding them here would give it a shortcut, and the shortcut would be the thing
        that drifts."""
        assert not [n for n in _SCHEMA.names if "expense" in n or "spend" in n]
