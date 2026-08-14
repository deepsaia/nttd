"""There is a live earnings series, not only the quarterly one that resets.

The Income chart plots ``GetQuarterlyIncome``, an accumulator the game resets at every quarter
boundary. So it climbs for three months, drops to nothing, and climbs again: it answers "how has
this quarter gone" and cannot answer "is the company earning right now". On a four quarter run
that is four sawteeth, and the drop looks like a collapse rather than a calendar.

Each vehicle's ``profit_this_year`` updates continuously and already nets its running cost, so
the fleet total is the live figure. Both are charted, and the quarterly one now says in its title
that it resets, because a reader cannot be expected to infer that from the shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nttd.analysis.loader import SessionData
from nttd.monitor.session_feed import SessionFeed


def _feed(snapshots: list[dict[str, Any]]) -> SessionFeed:
    import polars as pl

    frame = pl.DataFrame({"snapshot_json": [json.dumps(s) for s in snapshots]})
    return SessionFeed(SessionData(session_id="s", session_dir=Path("/tmp/s"), snapshots=frame))


def _snapshot(day: int, income: int, profits: list[int]) -> dict[str, Any]:
    return {
        "game": {"game_date": day},
        "companies": [{"name": "c", "income": income}],
        "stations": [],
        "vehicles": [{"id": i, "profit_this_year": p} for i, p in enumerate(profits)],
    }


def test_the_fleet_total_is_published_per_step() -> None:
    rows = _feed([
        _snapshot(737790, 100, [10, 20]),
        _snapshot(737791, 200, [15, 25, 5]),
    ]).steps()
    assert [r["fleet_profit"] for r in rows] == [30, 45]


def test_it_keeps_rising_across_a_quarter_boundary_where_income_resets() -> None:
    """The whole point: the quarterly series drops to zero and the live one does not."""
    rows = _feed([
        _snapshot(737880, 9000, [4000, 3000]),
        _snapshot(737881, 12, [4100, 3050]),
    ]).steps()
    assert rows[1]["income"] < rows[0]["income"], "the quarterly figure resets"
    assert rows[1]["fleet_profit"] > rows[0]["fleet_profit"], "the live figure must not"


def test_a_company_with_no_vehicles_reports_zero_rather_than_nothing() -> None:
    rows = _feed([_snapshot(737790, 0, [])]).steps()
    assert rows[0]["fleet_profit"] == 0


def test_losses_are_included_rather_than_clipped() -> None:
    """A fleet where the losers outweigh the earners must read negative."""
    rows = _feed([_snapshot(737790, 500, [1000, -1700, -600])]).steps()
    assert rows[0]["fleet_profit"] == -1300


def test_both_series_are_charted_and_the_resetting_one_says_so() -> None:
    from nttd.monitor.page import _SINGLE_CHARTS

    fields = {field: title for field, title in _SINGLE_CHARTS}
    assert "fleet_profit" in fields
    assert "live" in fields["fleet_profit"]
    assert "resets" in fields["income"]
