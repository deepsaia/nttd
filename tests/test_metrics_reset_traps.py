"""Metrics read from a quarterly accumulator must not be sampled on the boundary.

OpenTTD reports income, expenses and cargo for the quarter IN PROGRESS, and resets each at the
boundary. A 366 day run ends on 1 January, which is a boundary, so the last snapshot of every
run is a one or two day old partial quarter. Three metrics were read straight off it:

  operating_margin_final       taken at the last snapshot with any income
  maintenance_burden_final     same, and it came out at -21.39 where the ratio can only
                               sensibly be 0 to 1, because it divided upkeep by a partial
                               quarter's income
  profitable_vehicle_share     read the final snapshot, where profit_this_year has just reset
                               for every vehicle, so it was 0.00 across all eleven sessions
                               including ones whose aircraft each earned close to 50,000

The first two now use the last COMPLETE quarter. The third uses the peak, because the question
it answers is whether the company ran a fleet that paid for itself.
"""

from __future__ import annotations

from nttd.analysis.business_metrics import _last_complete_index


def test_the_last_complete_quarter_is_the_value_before_the_reset() -> None:
    """The measured shape: a quarter accumulates, then the run ends two days into the next."""
    income = [0, 4_000, 9_000, 12]
    assert _last_complete_index(income) == 2


def test_a_run_that_never_crossed_a_boundary_uses_its_last_snapshot() -> None:
    income = [0, 100, 400, 900]
    assert _last_complete_index(income) == 3


def test_several_quarters_take_the_most_recent_completed_one() -> None:
    income = [0, 500, 900, 10, 700, 1_500, 20]
    assert _last_complete_index(income) == 5


def test_an_empty_series_is_reported_as_absent_rather_than_guessed() -> None:
    assert _last_complete_index([]) == -1


def test_the_margin_is_taken_from_the_completed_quarter() -> None:
    """Straight from the fixed code path, so a regression shows up as a wrong number rather
    than as a passing test on a helper nothing calls."""
    from nttd.analysis.business_metrics import BusinessMetrics, _CompanySeries, _profitability

    series = _CompanySeries()
    series.income = [0, 5_000, 10_000, 12]
    series.expenses = [0, -1_000, -2_000, -50]
    series.maintenance = [0, 0, 0, 0]
    metrics = BusinessMetrics()
    _profitability(metrics, series)
    # The completed quarter: (10_000 - 2_000) / 10_000. The partial one would give -3.1667.
    assert metrics.operating_margin_final == 0.8
