"""Wall time reads as a clock, and the first table column does not wrap.

Both are display-only, and both were noticed by looking at the page rather than the code:

  * "127.4m" needs arithmetic before it means anything. Runs here span 45 minutes for a T1 to
    two hours for a T4, which is exactly the range where minutes stop being readable.
  * The action log's first column is a date like "05-Jan-1950". It wrapped onto a second line,
    doubling the height of every row in the table you scan most.
"""

from __future__ import annotations

import pytest

from nttd.monitor import assets
from nttd.monitor.charts import money
from nttd.monitor.page import _clock, _sidebar


@pytest.mark.parametrize(("minutes", "expected"), [
    (0, "00:00:00"),
    (0.5, "00:00:30"),
    (12.3, "00:12:18"),
    (45.0, "00:45:00"),
    (127.4, "02:07:24"),
])
def test_wall_time_is_hours_minutes_seconds(minutes: float, expected: str) -> None:
    assert _clock(minutes) == expected


def test_a_session_that_never_ran_reads_as_zero_not_as_an_error() -> None:
    assert _clock(None) == "00:00:00"


def test_the_unit_is_stated_where_the_number_is_shown() -> None:
    """A bare 02:07:24 could be read as a game date. The label carries the unit."""
    from nttd.monitor import page

    card = page._session_cards(
        {"rating": 25, "value": 1, "balance": 100, "stations": 8, "vehicles": 4,
         "days": 366, "steps": 378, "actions": 42, "refused": 12, "minutes": 43.9},
    )
    assert "wall time (hh:mm:ss)" in card
    assert "00:43:54" in card


def test_the_first_table_column_does_not_wrap() -> None:
    assert ".tbl th:first-child,.tbl td:first-child" in assets.CSS
    rule = assets.CSS.split(".tbl th:first-child,.tbl td:first-child")[1].split("}")[0]
    assert "nowrap" in rule


def test_one_row_of_panels_is_separated_from_the_next() -> None:
    """Otherwise a stack of rows reads as one undifferentiated field of boxes.

    The gap INSIDE a row is 12px. Between rows it is larger, which is the whole point: with
    both the same there is no telling where one row ends and the next begins.
    """
    assert ".grid + .grid" in assets.CSS, "rows of panels sit flush against each other"
    assert ".grid + .plot" in assets.CSS, "a panel following a row sits flush under it"

    rule = assets.CSS.split(".grid + .grid, .grid + .plot")[1].split("}")[0]
    assert "margin-top" in rule


def test_every_row_boundary_uses_the_same_gap() -> None:
    """Three boundaries on the page: the first band, then two rows of panels. A different
    gap at one of them reads as a mistake rather than as structure."""
    between = assets.CSS.split(".grid + .grid, .grid + .plot")[1].split("}")[0]
    under_first_band = assets.CSS.split(".split{")[1].split("}")[0]

    size = between.split("margin-top:")[1].split(";")[0].strip()
    assert f"margin-bottom:{size}" in under_first_band, (
        f"rows are {size} apart but the first band is not"
    )


# --- a company's worth, short enough to sit beside a day and a rating -------------------------


@pytest.mark.parametrize(("value", "expected"), [
    # The two the sidebar was asked for.
    (1_540_000, "$1.54M"),
    (250_000, "$250K"),
    # Thousands are whole. Two companies 400 apart are the same company at a glance, and
    # $250.4K spends a character on a distinction nobody reads there.
    (250_400, "$250K"),
    (12_345, "$12K"),
    (1_000, "$1K"),
    # Under a thousand there is nothing to shorten.
    (999, "$999"),
    (812, "$812"),
    (0, "$0"),
    # The sign goes outside the currency, which is how a negative balance is written and, more
    # usefully, how it is scanned: the minus is the first thing seen.
    (-4_200, "-$4K"),
    (-2_500_000, "-$2.50M"),
])
def test_a_company_value_is_shortened_the_way_it_is_read(value: int, expected: str) -> None:
    assert money(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    # 999,999 / 1000 rounded to no decimals is 1,000. Compared against the tier itself rather
    # than against what rounds INTO it, this printed $1,000K: a thousand thousands, which makes
    # the reader do exactly the arithmetic the shortening was supposed to save.
    (999_499, "$999K"),
    (999_500, "$1.00M"),
    (999_999, "$1.00M"),
    (1_000_000, "$1.00M"),
    # The same boundary one tier up, where two decimals mean 999,995,000 rounds to 1,000.00M.
    (999_994_999, "$999.99M"),
    (999_995_000, "$1.00B"),
    (2_400_000_000, "$2.40B"),
])
def test_a_value_never_rounds_into_a_tier_it_is_not_in(value: int, expected: str) -> None:
    assert money(value) == expected


def test_a_missing_value_is_a_dash_rather_than_zero() -> None:
    """A session with no snapshot yet has no value, which is not a company worth nothing."""
    assert money(None) == "-"


def test_something_that_is_not_a_number_is_passed_through_escaped() -> None:
    """A formatter is not the place to raise. It is rendering a page that is already late."""
    assert money("n/a") == "n/a"
    assert money("<b>") == "&lt;b&gt;"


def test_the_sidebar_shows_the_day_the_value_and_the_rating() -> None:
    """All three, because a rating alone does not say whether the company is worth anything.

    Two runs can hold the same rating with an order of magnitude between their values: the
    rating is bounded at 1000 and saturates, and the board ranks on value.
    """
    entries = [{"meta": {
        "session_id": "s-1", "name": "20260824-132212ist-sly-marsh", "live": False,
        "days": 366, "value": 1_540_000, "rating": 812, "ended": True,
    }}]
    html = _sidebar(entries, "s-1")
    assert "day 366" in html
    assert "$1.54M" in html
    assert "rating 812" in html
