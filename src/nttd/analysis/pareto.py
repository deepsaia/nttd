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


def cumulative_revenue(
    game_dates: Sequence[int], quarter_income: Sequence[float], *,
    finance_quarters: Sequence[int] | None = None,
    completed_quarter_income: Sequence[Sequence[float | None]] | None = None,
    last_completed_quarter_income: Sequence[float | None] | None = None,
    initial_income: float = 0,
) -> np.ndarray:
    """Revenue reconstructed from completed quarters, never partial-quarter maxima.

    New recordings provide the economy-quarter and history from the same GS read.
    Legacy recordings may provide only the last completed quarter (``income``).
    Their period labels are inferred from the game date and observed resets; that
    compatibility path is not an exact clock reconstruction. Missing completed
    quarters produce NaN instead of an invented total. Later authoritative history
    can recover earlier missing quarters in this retrospective analysis.
    """
    income = np.asarray(quarter_income, dtype=float)
    if income.size == 0:
        return income
    if len(game_dates) != income.size:
        raise ValueError("game_dates and quarter_income must have the same length")
    quarters = list(finance_quarters) if finance_quarters is not None else [
        year * 4 + (month - 1) // 3 for year, month, _ in map(game_date_to_ymd, game_dates)
    ]
    for optional in (finance_quarters, completed_quarter_income, last_completed_quarter_income):
        if optional is not None and len(optional) != income.size:
            raise ValueError("financial series must have the same length")
    if finance_quarters is None and last_completed_quarter_income is not None and any(
        value is not None for value in last_completed_quarter_income
    ):
        # Historical snapshot dates sometimes advanced before the financial read.
        # Keep the prior period until a reset/history change is observed. A zero
        # quarter can roll into another zero quarter without a downward step.
        current = quarters[0]
        for row in range(1, len(quarters)):
            old_q1, q1 = last_completed_quarter_income[row - 1:row + 1]
            if quarters[row] > current and (
                income[row] < income[row - 1] or q1 != old_q1
                or (income[row - 1] == 0 and q1 == 0)
            ):
                current = quarters[row]
            quarters[row] = current
    completed: dict[int, float] = {}
    for row, quarter in enumerate(quarters):
        history = completed_quarter_income[row] if completed_quarter_income is not None else []
        if not history and last_completed_quarter_income is not None:
            history = [last_completed_quarter_income[row]]
        for offset, value in enumerate(history, 1):
            if value is not None and np.isfinite(value):
                completed[quarter - offset] = float(value)
    totals = np.full(income.size, np.nan)
    for row, quarter in enumerate(quarters):
        if quarter >= quarters[0] and all(q in completed for q in range(quarters[0], quarter)):
            totals[row] = sum(completed[q] for q in range(quarters[0], quarter)) + income[row] - initial_income
    return totals


def episode_revenue(game_dates: Sequence[int], quarter_income: Sequence[float], **kwargs) -> int | None:
    """The income of the whole episode, the last value of cumulative_revenue."""
    total = cumulative_revenue(game_dates, quarter_income, **kwargs)
    return int(total[-1]) if total.size and np.isfinite(total[-1]) else (None if total.size else 0)


def pareto_fronts(points: Mapping[str, Sequence[float]]) -> dict[str, int]:
    """The front of each named point, 1 for the points nobody dominates. Every axis is maximized.

    Equal points share a front.
    """
    names = list(points)
    if not names:
        return {}
    values = np.asarray([points[name] for name in names], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Pareto ranking requires every metric; missing revenue is not zero")
    ranks = pareto_rank(values, maximise=True)
    return {name: int(rank) + 1 for name, rank in zip(names, ranks)}
