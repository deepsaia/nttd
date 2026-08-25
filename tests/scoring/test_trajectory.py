"""The series the board charts a run from.

It derives nothing: one row per snapshot, each figure as the game reported it. It came out
with a module of derived business metrics that went for being derived, which was a mistake,
because the board had been reading it all along and every verification then failed on
`ImportError: cannot import name 'business_metrics'`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.analysis.trajectory import trajectory_rows


def _write(session_dir: Path, snapshots: list[tuple[int, dict]]) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({
            "game_date": [date for date, _ in snapshots],
            "snapshot_json": [json.dumps(snap) for _, snap in snapshots],
        }),
        session_dir / "snapshots.parquet",
    )


def _company(**fields: int) -> dict:
    base = {
        "id": 0, "value": 0, "money": 0, "loan": 0, "max_loan": 0,
        "q0_income": 0, "q0_expenses": 0, "cargo_delivered_total": 0,
        "vehicles": 0, "stations": 0, "profitable_vehicles": 0,
        "idle_vehicles": 0, "maintenance": 0,
    }
    base.update(fields)
    return base


def test_one_row_per_snapshot_with_the_figures_as_reported(tmp_path: Path) -> None:
    _write(tmp_path, [
        (100, {"companies": [_company(value=1_000, money=500)]}),
        (101, {"companies": [_company(value=2_000, money=400)]}),
    ])
    rows = trajectory_rows(tmp_path, 0)

    assert [r["game_date"] for r in rows] == [100, 101]
    assert [r["value"] for r in rows] == [1_000, 2_000]
    assert [r["money"] for r in rows] == [500, 400]


def test_cargo_is_the_run_total_and_not_the_quarter_in_progress(tmp_path: Path) -> None:
    """q0_cargo resets at every quarter boundary and a run ENDS on one.

    A measured run that delivered 3,526 units across its year charted as zero, because the
    counter had just gone back to nothing at the moment it was read. The GameScript banks a
    running total precisely so nothing has to reconstruct it.
    """
    _write(tmp_path, [
        (100, {"companies": [_company(cargo_delivered_total=370, q0_cargo=370)]}),
        (200, {"companies": [_company(cargo_delivered_total=3_526, q0_cargo=0)]}),
    ])
    assert [r["cargo"] for r in trajectory_rows(tmp_path, 0)] == [370, 3_526]


def test_it_reads_the_company_asked_for(tmp_path: Path) -> None:
    """The typed c0_ columns cover company 0 only, which is why this reads the JSON."""
    _write(tmp_path, [(100, {"companies": [
        _company(id=0, value=1), {**_company(id=1, value=99), "id": 1},
    ]})])
    assert trajectory_rows(tmp_path, 1)[0]["value"] == 99


def test_a_snapshot_without_that_company_is_skipped(tmp_path: Path) -> None:
    """Taken before the company existed. A row of zeros there would draw as a collapse."""
    _write(tmp_path, [
        (100, {"companies": []}),
        (101, {"companies": [_company(value=5)]}),
    ])
    rows = trajectory_rows(tmp_path, 0)
    assert len(rows) == 1
    assert rows[0]["game_date"] == 101


def test_a_missing_series_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    """A run whose snapshots did not survive still has a score worth publishing, and a
    verdict that fails to write because a chart could not be drawn is the wrong trade."""
    assert trajectory_rows(tmp_path / "nothing-here", 0) == []


def test_a_torn_snapshot_is_skipped_rather_than_fatal(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"game_date": [100, 101],
                  "snapshot_json": ['{"companies": [{"id": 0, "value": 7', None]}),
        tmp_path / "snapshots.parquet",
    )
    assert trajectory_rows(tmp_path, 0) == []


def test_every_field_the_board_charts_is_present(tmp_path: Path) -> None:
    """The board writes these straight to trajectories.parquet, so a dropped key is a
    column that silently disappears from the published dataset."""
    _write(tmp_path, [(100, {"companies": [_company()]})])
    row = trajectory_rows(tmp_path, 0)[0]
    assert set(row) == {
        "game_date", "value", "money", "loan", "max_loan", "income", "expenses",
        "cargo", "vehicles", "stations", "profitable_vehicles", "idle_vehicles",
        "maintenance",
    }
