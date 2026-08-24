"""What a run said its models cost, and the runs that said nothing.

nttd cannot observe a token or a dollar, so every figure here is the contestant's claim
about itself. The panel exists because a total says what a run cost and a series says where
it went, and the second is the one worth watching while a run is still going.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from nttd.analysis.loader import SessionData
from nttd.monitor.page import _spend_panels
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
    assert _spend_panels(empty.spend()) == []


def test_an_empty_dict_draws_nothing_rather_than_an_empty_chart() -> None:
    assert _spend_panels({}) == []
    assert _spend_panels({"models": []}) == []


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


def test_the_series_is_cumulative_and_measured_in_game_days() -> None:
    """The question is what the run has cost BY NOW, and the x axis is the game's clock.

    Day zero is the first report, not the first snapshot: this series is about spend, and
    a runner that declares nothing until day 50 has spent nothing before it.
    """
    spend = _spend([
        (737_790, 0, "m", "anthropic", 100, 10, 1.0),
        (737_800, 0, "m", "anthropic", 100, 10, 2.0),
        (737_820, 0, "m", "anthropic", 100, 10, 3.0),
    ])
    assert [(p["day"], p["cost"]) for p in spend["series"]] == [(0, 1.0), (10, 3.0), (30, 6.0)]
    assert [p["tokens"] for p in spend["series"]] == [110, 220, 330]


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
    html = "".join(_spend_panels(_spend([
        (100, 0, "unpriced", "anthropic", 9_000, 900, None),
    ])))
    assert "not priced" in html
    assert "$0.00" not in html, "a withheld price must not render as free"


def test_the_panel_says_the_figures_are_the_contestants_own() -> None:
    """nttd runs no model. Presenting these beside counts it tallied itself would imply
    it checked them."""
    html = "".join(_spend_panels(_spend([(100, 0, "m", "anthropic", 10, 1, 0.5)])))
    assert "unverifiable" in html
