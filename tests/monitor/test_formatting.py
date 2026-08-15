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
from nttd.monitor.page import _clock


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
         "steps": 366, "actions": 42, "refused": 12, "minutes": 43.9},
    )
    assert "wall time (hh:mm:ss)" in card
    assert "00:43:54" in card


def test_the_first_table_column_does_not_wrap() -> None:
    assert ".tbl th:first-child,.tbl td:first-child" in assets.CSS
    rule = assets.CSS.split(".tbl th:first-child,.tbl td:first-child")[1].split("}")[0]
    assert "nowrap" in rule
