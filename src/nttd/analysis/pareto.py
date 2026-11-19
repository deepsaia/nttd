"""Pareto ranking of company results over the benchmark's four axes.

A result is one point with four axes, all maximized: company value, revenue over the
episode, cargo delivered and performance rating. A point is dominated when another
point is at least as good on every axis and better on one. Front 1 holds the points
nobody dominates. Front 2 holds the points dominated only by front 1, and so on. The
front number is the score of the point. Compare means over seeds, never single runs.

Company value already has the loan subtracted, and the game floors it at 1, so every
company that owes more than it owns ties on that axis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from moocore import pareto_rank

from nttd.analysis.date_utils import game_date_to_ymd

AXES = ("company_value", "episode_revenue", "total_cargo", "performance_rating")


def cumulative_revenue(game_dates: Sequence[int], quarter_income: Sequence[float]) -> np.ndarray:
    """The income of the episode so far at each day.

    The game reports the income of the quarter in progress. It restarts at each quarter
    boundary, so a decrease marks a new quarter and the value just before it is the income
    of the completed quarter. A decrease counts only when the game date is in a later
    quarter than the previous one counted, so a negative payment inside a quarter does not
    count. The date may run a few days ahead of the income record.
    """
    income = np.asarray(quarter_income, dtype=float)
    if income.size == 0:
        return income
    quarters = [year * 4 + (month - 1) // 3 for year, month, _ in map(game_date_to_ymd, game_dates)]
    completed = np.zeros(income.size)
    banked, last_quarter = 0.0, quarters[0]
    for row in range(1, income.size):
        if income[row] < income[row - 1] and quarters[row] > last_quarter:
            banked += income[row - 1]
            last_quarter = quarters[row]
        completed[row] = banked
    return completed + income


def episode_revenue(game_dates: Sequence[int], quarter_income: Sequence[float]) -> int:
    """The income of the whole episode, the last value of cumulative_revenue."""
    total = cumulative_revenue(game_dates, quarter_income)
    return int(total[-1]) if total.size else 0


def pareto_fronts(points: Mapping[str, Sequence[float]]) -> dict[str, int]:
    """The front of each named point, 1 for the points nobody dominates. Every axis is maximized.

    Equal points share a front.
    """
    names = list(points)
    if not names:
        return {}
    ranks = pareto_rank(np.asarray([points[name] for name in names], dtype=float), maximise=True)
    return {name: int(rank) + 1 for name, rank in zip(names, ranks)}
