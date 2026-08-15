"""Cargo delivered is a running total, not a reading of a counter that resets.

OpenTTD reports GetQuarterlyCargoDelivered for the quarter IN PROGRESS, so the series sawtooths:
it climbs through a quarter and drops to zero at the boundary. Every cargo figure in the result
was a point sample of that raw counter.

Two ways that went wrong at once, and both were silent:

  * The growth checkpoints sample at 25, 50 and 75 percent of the run. On a 366 day run those
    fractions land within a day or two of the quarter boundaries, exactly where the counter has
    just reset. All three read 0.
  * The efficiency metrics used the LAST reading, and a run ending on a quarter boundary reads 0
    there too.

Measured on a real completed session, ses_20260813_214540_7e125597: per-quarter peaks of 370,
885, 1216 and 1055, so 3,526 units delivered across the year. The result reported 0 for every
cargo column, and cargo is both a leaderboard column and the scoring tiebreak.
"""

from __future__ import annotations

from nttd.analysis.business_metrics import _cumulative_cargo


def test_a_quarterly_counter_becomes_a_running_total() -> None:
    """The shape the real run had: four quarters, each climbing then resetting."""
    quarterly = [0, 100, 370, 0, 400, 885, 0, 900, 1216, 0, 500, 1055, 0]
    running = _cumulative_cargo(quarterly)

    assert running[-1] == 3526, "the year total from the measured session"
    # Never goes backwards, which is the property a cumulative series must have.
    assert all(b >= a for a, b in zip(running, running[1:]))


def test_the_total_survives_ending_on_a_quarter_boundary() -> None:
    """The specific failure. The last raw reading is 0; the total is not."""
    quarterly = [0, 500, 900, 0]
    assert quarterly[-1] == 0
    assert _cumulative_cargo(quarterly)[-1] == 900


def test_a_checkpoint_on_a_reset_reports_what_was_carried() -> None:
    """The other specific failure: sampling at a fraction that lands on a boundary.

    Index 3 is a reset in this series. The raw value there is 0; the run had delivered 370.
    """
    quarterly = [0, 100, 370, 0, 400]
    running = _cumulative_cargo(quarterly)
    assert quarterly[3] == 0
    assert running[3] == 370


def test_a_run_that_never_carried_anything_reports_zero() -> None:
    assert _cumulative_cargo([0, 0, 0])[-1] == 0
    assert _cumulative_cargo([]) == []


def test_a_single_quarter_still_in_progress_counts() -> None:
    """A run shorter than a quarter has no reset, so the total is simply the reading."""
    assert _cumulative_cargo([0, 40, 120])[-1] == 120
