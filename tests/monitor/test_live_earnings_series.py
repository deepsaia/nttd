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


def test_the_charted_series_survives_the_year_boundary() -> None:
    """profit_this_year resets on 1 January, and a T1 run ENDS on 1 January.

    Measured on ses_20260814_183927_6160d8b7: the live sum read 174,449 on 30-Dec-2020 and
    -20 on the next step, so the chart collapsed to zero on its final point. The cumulative
    series banks each closed year and keeps climbing.
    """
    rows = _feed([
        _snapshot(738_154, 9000, [174_000, 449]),
        _snapshot(738_156, 12, [-10, -10]),
    ]).steps()
    assert rows[1]["fleet_profit"] == -20, "the live figure does reset, and says so"
    assert rows[1]["fleet_profit_total"] == 174_429, "the cumulative figure does not"


def test_a_crashed_vehicle_is_not_banked_as_a_closed_year() -> None:
    """The sum also drops when a vehicle dies. Banking on any DROP would double count it,
    so the year is read from the game date instead."""
    rows = _feed([
        _snapshot(737_800, 100, [5000, 4000]),
        _snapshot(737_801, 100, [5000]),
    ]).steps()
    assert rows[1]["fleet_profit_total"] == 5000, "same year, so nothing is banked"


def test_both_series_are_charted_and_the_resetting_one_says_so() -> None:
    from nttd.monitor.page import _SINGLE_CHARTS

    fields = dict(_SINGLE_CHARTS)
    assert "fleet_profit_total" in fields
    assert "cumulative" in fields["fleet_profit_total"]
    assert "resets" in fields["income"]


def test_orders_and_routes_are_counted_per_step() -> None:
    """Two vehicles sharing one order list are ONE route, not two: the useful question is how
    much of the map is served, and a third bus on one pair serves no more of it."""
    import polars as pl

    from nttd.analysis.loader import SessionData

    def stop(dest: int) -> dict[str, Any]:
        return {"index": 0, "destination": dest, "is_goto_station": True}

    snapshot = {
        "game": {"game_date": 737_800},
        "companies": [{"name": "c"}],
        "stations": [],
        "vehicles": [
            {"id": 0, "type": "aircraft", "orders": [stop(10), stop(20)]},
            {"id": 1, "type": "aircraft", "orders": [stop(20), stop(10)]},
            {"id": 2, "type": "aircraft", "orders": [stop(30), stop(40)]},
            {"id": 3, "type": "aircraft", "orders": []},
        ],
    }
    frame = pl.DataFrame({"snapshot_json": [json.dumps(snapshot)]})
    rows = SessionFeed(
        SessionData(session_id="s", session_dir=Path("/tmp/s"), snapshots=frame),
    ).steps()
    assert rows[0]["routes_distinct"] == 2, "the shared pair counts once"
    assert rows[0]["orders_total"] == 6
    assert rows[0]["vehicles_idle"] == 1, "a vehicle with no orders is the clone failure"
