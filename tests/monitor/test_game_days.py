"""The day count the monitor shows is the game's, not a count of rows.

Measured on a real run: session 20260824-132212ist-sly-marsh played exactly 366 game days,
737790 to 738156, and its result record says `game_days = 366` with
`end_reason = "Max heartbeats reached (366)"`. Its snapshots.parquet holds **378** rows over
**367** distinct dates, because a day on which the runner acted more than once is captured
more than once.

The page labelled that row count "days", so it reported 378 for a run whose scored record says
366. Nothing was wrong with the run or the score. But a reader comparing the two has no way to
know which is the lie, and the number they are being asked to trust is the scored one.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from nttd.analysis.loader import SessionData
from nttd.monitor.session_feed import SessionFeed


def _feed(dates: list[int], **fields: object) -> SessionFeed:
    # The date lives in two places for two readers: the parquet column, which game_days()
    # uses because it needs no parsing, and inside the snapshot, which steps() reads because
    # it is already decoding the whole thing for the charts.
    frame = pl.DataFrame({
        "game_date": dates,
        "snapshot_json": [
            json.dumps({"game": {"game_date": date}, "companies": [{}]}) for date in dates
        ],
    })
    data = SessionData(
        session_id="a-session", session_dir=Path("/nonexistent"), snapshots=frame, **fields,
    )
    return SessionFeed(data)


def test_a_day_captured_twice_is_still_one_day() -> None:
    """The exact shape of the real run, reduced: 5 days, 6 snapshots."""
    feed = _feed([100, 101, 102, 102, 103, 105])
    assert feed.step_count() == 6
    assert feed.game_days() == 5


def test_the_span_is_inclusive_of_neither_end_twice() -> None:
    """A run of N days visits N+1 distinct dates, so the span is max minus min."""
    assert _feed([737790, 738156]).game_days() == 366


def test_a_run_that_has_not_started_reports_no_days() -> None:
    assert _feed([737790]).game_days() == 0


def test_the_page_reports_days_and_not_snapshots() -> None:
    """Three places on the page show this number, and all three said 'day'."""
    feed = _feed([100, 101, 102, 102, 103, 105])
    meta = feed.meta()
    assert meta["days"] == 5
    assert meta["steps"] == 6, "the snapshot count is still available for the scrubber"


def test_an_empty_session_does_not_divide_by_anything() -> None:
    frame = pl.DataFrame({"game_date": [], "snapshot_json": []})
    data = SessionData(session_id="s", session_dir=Path("/nonexistent"), snapshots=frame)
    assert SessionFeed(data).game_days() == 0


def test_the_charts_plot_against_the_game_day() -> None:
    """The same defect as the sidebar's, in the one place that survived the first fix.

    Every chart shares one x field. It was the snapshot index, so a run whose cargo chart
    read "day 378" had a result record saying 366. The fix landed for the sidebar, the index
    table, the cards and the map scrubber, and silently did not land here.
    """
    feed = _feed([737790, 737791, 737792, 737792, 737795])
    days = [row["day"] for row in feed.steps()]
    assert days == [0, 1, 2, 2, 5], "the x axis is the game day, not the row position"


def test_a_chart_reads_the_day_field_and_not_the_row_position() -> None:
    """Asserted on the chart itself, because the series and the chart have to agree.

    Renaming one without the other draws an empty panel rather than a wrong one, which at
    least fails loudly, but only if something looks.
    """
    from nttd.monitor.charts import line_chart  # noqa: PLC0415

    rows = [{"day": day, "v": day} for day in (0, 10, 20)]
    drawn = line_chart("t", [{"label": "v", "colour": "#fff", "rows": rows}], "T", "v")
    assert "<circle" in drawn or "polyline" in drawn, "nothing was plotted"

    stale = [{"step": index, "v": index} for index in range(3)]
    empty = line_chart("t", [{"label": "v", "colour": "#fff", "rows": stale}], "T", "v")
    assert "no data" in empty, "the chart must key on day, so a step-keyed row plots nothing"
