"""Tests for the Pareto ranking of results.

Run with: uv run pytest tests/scoring/test_pareto.py -v
"""

from __future__ import annotations

from nttd.analysis.pareto import AXES, cumulative_revenue, episode_revenue, pareto_fronts


def test_the_four_axes_are_the_benchmark_axes() -> None:
    assert AXES == ("company_value", "episode_revenue", "total_cargo", "performance_rating")


def test_a_point_better_on_every_axis_is_alone_on_front_one() -> None:
    fronts = pareto_fronts({"a": (2, 2, 2, 2), "b": (1, 1, 1, 1)})
    assert fronts == {"a": 1, "b": 2}


def test_points_that_trade_axes_share_front_one() -> None:
    fronts = pareto_fronts({"value": (10, 1, 1, 1), "cargo": (1, 1, 10, 1), "worse": (0, 0, 0, 0)})
    assert fronts == {"value": 1, "cargo": 1, "worse": 2}


def test_a_point_better_on_one_axis_and_equal_elsewhere_dominates() -> None:
    fronts = pareto_fronts({"a": (1, 1, 1, 2), "b": (1, 1, 1, 1)})
    assert fronts == {"a": 1, "b": 2}


def test_equal_points_share_a_front() -> None:
    fronts = pareto_fronts({"a": (1, 1, 1, 1), "b": (1, 1, 1, 1), "c": (0, 0, 0, 0)})
    assert fronts == {"a": 1, "b": 1, "c": 2}


def test_fronts_go_as_deep_as_the_chain() -> None:
    fronts = pareto_fronts({str(level): (level,) * 4 for level in range(5)})
    assert fronts == {"4": 1, "3": 2, "2": 3, "1": 4, "0": 5}


def test_no_points_give_no_fronts() -> None:
    assert pareto_fronts({}) == {}


# Game date 715966 is 1 April 1960, the first day of a quarter.
MARCH_26 = 715960


def days(count: int, start: int = MARCH_26) -> list[int]:
    return list(range(start, start + count))


def test_cumulative_revenue_banks_each_quarter_at_its_boundary() -> None:
    income = [100, 150, 150, 200, 200, 250, 0, 30, 30, 80]
    assert cumulative_revenue(days(10), income).tolist() == [100, 150, 150, 200, 200, 250, 250, 280, 280, 330]


def test_a_decrease_inside_a_quarter_is_not_a_new_quarter() -> None:
    income = [100, 150, 120, 180]
    assert cumulative_revenue(days(4), income).tolist() == [100, 150, 120, 180]


def test_an_income_record_a_few_days_behind_the_date_still_banks_once() -> None:
    """In a real-time game the income restarts two to five days after the date changed quarter."""
    income = [200, 250, 250, 250, 250, 250, 250, 250, 0, 40]
    assert cumulative_revenue(days(10), income).tolist() == [200, 250, 250, 250, 250, 250, 250, 250, 250, 290]


def test_episode_revenue_is_the_last_cumulative_value() -> None:
    assert episode_revenue(days(10), [100, 150, 150, 200, 200, 250, 0, 30, 30, 80]) == 330


def test_episode_revenue_of_nothing_is_zero() -> None:
    assert episode_revenue([], []) == 0
    assert cumulative_revenue([], []).size == 0
