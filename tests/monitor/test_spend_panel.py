"""What a run said its models cost, and the runs that said nothing.

nttd cannot observe a token or a dollar, so every figure here is the contestant's claim
about itself. The panel exists because a total says what a run cost and a series says where
it went, and the second is the one worth watching while a run is still going.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from nttd.analysis.loader import SessionData
from nttd.monitor.page import _spend_charts, _spend_table
from nttd.monitor.session_feed import SessionFeed

_COLUMNS = (
    "game_date", "company_id", "model", "role",
    "prompt_tokens", "completion_tokens", "total_cost_usd",
)


def _feed(rows: list[tuple]) -> SessionFeed:
    frame = pl.DataFrame(
        {name: [row[index] for row in rows] for index, name in enumerate(_COLUMNS)},
        schema_overrides={"total_cost_usd": pl.Float64},
    )
    data = SessionData(session_id="s", session_dir=Path("/nonexistent"), spend=frame)
    return SessionFeed(data)


def _spend(rows: list[tuple]) -> dict:
    return _feed(rows).spend()


# --- the runs that report nothing ------------------------------------------------------


def test_a_run_that_reported_nothing_has_no_panel_at_all() -> None:
    """An RL or ES entry runs a policy, not a model, and has no tokens to declare.

    A chart of zeros for it would not be a fact about the run, it would be a fact about the
    absence of a report, and the page has somewhere else to say that.
    """
    empty = SessionFeed(SessionData(session_id="s", session_dir=Path("/nonexistent")))
    assert empty.spend() == {}
    assert _spend_charts(empty.spend()) == []
    assert _spend_table(empty.spend()) == []


def test_an_empty_dict_draws_nothing_rather_than_an_empty_chart() -> None:
    for empty in ({}, {"models": []}):
        assert _spend_charts(empty) == []
        assert _spend_table(empty) == []


# --- what an agent run shows -----------------------------------------------------------


def test_usage_is_summed_per_model() -> None:
    """A front man on one model and workers on another is the split worth seeing."""
    spend = _spend([
        (100, 0, "opus", "anthropic", 1_000, 100, 1.0),
        (110, 0, "opus", "anthropic", 2_000, 200, 2.0),
        (110, 0, "sonnet", "anthropic", 500, 50, 0.1),
    ])
    per_model = {m["model"]: m for m in spend["models"]}
    assert per_model["opus"]["prompt_tokens"] == 3_000
    assert per_model["opus"]["cost"] == 3.0
    assert per_model["opus"]["reports"] == 2
    assert spend["cost"] == 3.1


def test_the_dearest_model_is_listed_first() -> None:
    """It is the lever: on a measured run the strategist was 92% of the bill."""
    spend = _spend([
        (100, 0, "cheap", "anthropic", 10, 1, 0.01),
        (100, 0, "dear", "anthropic", 10, 1, 9.99),
    ])
    assert [m["model"] for m in spend["models"]] == ["dear", "cheap"]


def test_the_series_is_per_day_and_measured_in_game_days() -> None:
    """What each turn cost, not what the run has cost by now, and on the game's clock.

    A running total only ever goes up, so every turn looks like progress and a turn costing
    four times the last one is a slightly steeper piece of the same climb. Per day that turn is
    four times the height, which is the thing worth seeing. The totals are not lost: the
    per-model table under these charts carries them.

    With no snapshot series to say when the run opened, the first report is the only origin
    available and the series starts there. A run WITH snapshots starts at day zero instead,
    which the tests below cover.
    """
    spend = _spend([
        (737_790, 0, "m", "anthropic", 100, 10, 1.0),
        (737_800, 0, "m", "anthropic", 100, 10, 2.0),
        (737_820, 0, "m", "anthropic", 100, 10, 3.0),
    ])
    series = {p["day"]: p for p in spend["series"]}
    assert len(series) == 31, "one point per day, not one per report"
    assert [series[day]["cost"] for day in (0, 9, 10, 19, 20, 30)] == [
        1.0, 0.0, 2.0, 0.0, 0.0, 3.0,
    ], "each turn's own cost on the day it ended, and nothing on the days between"
    assert series[30]["tokens"] == 110, "that turn's tokens, not the run's"
    assert spend["turn_days"] == [0, 10, 30]
    # The totals still add up to what the table shows.
    assert sum(p["cost"] for p in spend["series"]) == 6.0
    assert spend["cost"] == 6.0


# --- tokens counted, price unknown ------------------------------------------------------


def test_an_unpriced_model_counts_its_tokens_and_withholds_the_money() -> None:
    """A null cost is not zero. It means the tokens are known and the price is not."""
    spend = _spend([
        (100, 0, "priced", "anthropic", 1_000, 100, 5.0),
        (100, 0, "unpriced", "anthropic", 9_000, 900, None),
    ])
    per_model = {m["model"]: m for m in spend["models"]}
    assert per_model["unpriced"]["priced"] is False
    assert per_model["unpriced"]["prompt_tokens"] == 9_000
    assert per_model["unpriced"]["cost"] == 0.0
    assert spend["prompt_tokens"] == 10_000, "the tokens still add up"
    assert spend["priced"] is False, "one unpriced model withholds the whole total"


def test_the_panel_says_not_priced_rather_than_a_dollar_total() -> None:
    """A total missing one of its parts still reads as a total."""
    html = "".join(_spend_table(_spend([
        (100, 0, "unpriced", "anthropic", 9_000, 900, None),
    ])))
    assert "not priced" in html
    assert "$0.00" not in html, "a withheld price must not render as free"


def test_the_panel_says_the_figures_are_the_contestants_own() -> None:
    """nttd runs no model. Presenting these beside counts it tallied itself would imply
    it checked them."""
    html = "".join(_spend_table(_spend([(100, 0, "m", "anthropic", 10, 1, 0.5)])))
    assert "unverifiable" in html


# --- a point per day, and where the turns were ---------------------------------------------


def _feed_over(dates: list[int], rows: list[tuple]) -> SessionFeed:
    """A spend frame plus a snapshot series, so the run's own day range is known."""
    import json  # noqa: PLC0415

    snaps = pl.DataFrame({
        "game_date": dates,
        "snapshot_json": [json.dumps({"game": {"game_date": d}, "companies": [{}]}) for d in dates],
    })
    spend = pl.DataFrame(
        {name: [row[index] for row in rows] for index, name in enumerate(_COLUMNS)},
        schema_overrides={"total_cost_usd": pl.Float64},
    )
    data = SessionData(
        session_id="s", session_dir=Path("/nonexistent"), snapshots=snaps, spend=spend,
    )
    return SessionFeed(data)


def test_there_is_a_point_for_every_day_of_the_run() -> None:
    """Spend only changes when a turn ends, and a turn covers many days.

    Plotted per report it is a handful of points scattered across a year with nothing between
    them, so there is a point on every day and the x axis stays the run's own clock, shared
    with every other chart on the page.
    """
    feed = _feed_over(
        list(range(100, 111)),                      # eleven days of run
        [(105, 0, "m", "anthropic", 10, 1, 2.0)],   # one turn, ending on day 5
    )
    series = feed.spend()["series"]
    assert [p["day"] for p in series] == list(range(11)), "one point per game day"


def test_the_line_sits_at_nothing_until_the_first_turn_ends() -> None:
    """Day zero is when the RUN opened, not when the first report arrived.

    Measuring from the first report puts the opening turn at day 0 and hides however long it
    took, and the honest picture is nothing at all until a turn lands.
    """
    feed = _feed_over(list(range(100, 111)), [(105, 0, "m", "anthropic", 10, 1, 2.0)])
    series = feed.spend()["series"]
    assert [p["cost"] for p in series[:5]] == [0.0] * 5
    assert series[5]["cost"] == 2.0, "the whole of that turn's cost, on the day it ended"
    assert series[-1]["cost"] == 0.0, "and nothing after it: no turn ended that day"


def test_the_turn_days_are_reported_for_the_markers() -> None:
    feed = _feed_over(
        list(range(100, 121)),
        [(105, 0, "m", "anthropic", 10, 1, 1.0), (115, 0, "m", "anthropic", 10, 1, 1.0)],
    )
    spend = feed.spend()
    assert spend["turn_days"] == [5, 15]
    by_day = {p["day"]: p["cost"] for p in spend["series"]}
    assert by_day[5] == 1.0 and by_day[15] == 1.0
    assert by_day[20] == 0.0, "the last day of the run ended no turn"
    assert spend["cost"] == 2.0, "the total is still reported, for the table"


def test_two_models_reporting_on_one_day_are_one_turn() -> None:
    """A turn reports once per model, so the day must not be counted twice as two steps."""
    feed = _feed_over(
        list(range(100, 111)),
        [(105, 0, "opus", "anthropic", 10, 1, 1.0), (105, 0, "sonnet", "anthropic", 10, 1, 0.5)],
    )
    spend = feed.spend()
    assert spend["turn_days"] == [5], "one turn, not two"
    assert spend["series"][5]["cost"] == 1.5, "both models land on the same step"


def test_the_charts_draw_a_rule_for_each_turn() -> None:
    feed = _feed_over(
        list(range(100, 121)),
        [(105, 0, "m", "anthropic", 10, 1, 1.0), (115, 0, "m", "anthropic", 10, 1, 1.0)],
    )
    html = "".join(_spend_charts(feed.spend()))
    assert html.count('class="mark"') == 4, "two turns, on each of two charts"


def test_a_run_reporting_every_day_draws_no_rules_at_all() -> None:
    """One rule per day is a solid block rather than a reading aid, and past that density
    the cadence is legible from the line itself."""
    from nttd.monitor.charts import _MOST_MARKS  # noqa: PLC0415

    days = list(range(100, 100 + _MOST_MARKS + 10))
    feed = _feed_over(days, [(d, 0, "m", "anthropic", 1, 1, 0.01) for d in days])
    html = "".join(_spend_charts(feed.spend()))
    assert 'class="mark"' not in html
