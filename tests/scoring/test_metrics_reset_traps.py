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

import inspect

from nttd import resources
from nttd.analysis.business_metrics import _last_complete_index
from nttd.state.world import WorldState


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


def test_the_scored_cargo_total_is_banked_by_the_gamescript_not_read_back() -> None:
    """The same reset trap, one layer down, and the only one that reached the leaderboard.

    total_cargo reads cargo_delivered_total, which used to sum GetQuarterlyCargoDelivered over
    the quarters the game keeps. Measured at 1960-12-15, three quarter ends into a run: quarter
    0 gave 1232 and quarters 1 upwards all gave 0, so the sum was 0 and a session that carried
    thousands scored no cargo at all. Quarter 0 is the only one the game answers for cargo,
    which is the reverse of GetQuarterlyPerformanceRating, so the GameScript banks quarter 0
    itself at each drop.
    """
    source = (resources.gamescript_dir() / "game" / "nttd-gs" / "main.nut").read_text()

    body = source.split("function _CargoDeliveredTotal")[1].split("function ")[0]
    code = [line for line in body.splitlines() if not line.lstrip().startswith("//")]
    assert "_cargo_banked" in body and "_cargo_last_q0" in body
    assert not any("GetQuarterlyCargoDelivered" in line for line in code), "the history read 0"
    # Declared on the class, or Squirrel refuses to create the slot and the script dies.
    for slot in ("_cargo_banked = null;", "_cargo_last_q0 = null;"):
        assert slot in source, slot


def test_every_scored_company_field_survives_the_world_refresh() -> None:
    """The second half of the same bug, and on its own it was enough to score 0.

    WorldState.apply_gs_companies copies a whitelist of keys out of the GameScript reply.
    cargo_delivered_total was missing from it, so the Company kept the model default of 0 and
    the result row read 0 no matter what the game sent. Fixing the GameScript alone changed
    nothing. Anything the score reads has to be on that list.
    """
    from nttd.analysis.score import score_company

    scoring = inspect.getsource(score_company)
    scored = {name for name in ("performance_rating", "cargo_delivered_total")
              if f"company.{name}" in scoring}
    assert scored == {"performance_rating", "cargo_delivered_total"}, scoring

    refresh = inspect.getsource(WorldState.apply_gs_companies)
    for field in sorted(scored):
        assert f'"{field}"' in refresh, f"{field} is scored but the world drops it"
