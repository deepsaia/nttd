"""Convert OpenTTD game dates (days since year 0) to calendar years.

The admin port reports the date as a day count with no year, so anything that
reasons about the calendar has to derive it. The naive ``game_date // 365``
is wrong by 2-3 years at OpenTTD's usual start dates because it ignores leap
days: day 716232 is 23 Dec 1960, but the naive form gives 1963.

This module is deliberately dependency-free so the runtime can use it. The
richer formatting helpers in ``nttd.analysis.date_utils`` pull in polars and are
for reporting only.
"""

from __future__ import annotations

_DAYS_PER_400_YEARS = 146097


def is_leap_year(year: int) -> bool:
    """Gregorian leap rule, which is what OpenTTD uses."""
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def game_date_to_year(game_date: int) -> int:
    """Return the calendar year containing ``game_date``.

    Args:
        game_date: Days since year 0, as reported by OpenTTD.

    Returns:
        The calendar year. Negative inputs return 0, since OpenTTD has no
        dates before year 0.
    """
    if game_date <= 0:
        return 0

    # Skip whole 400-year cycles first; each is exactly 146097 days.
    year = (game_date // _DAYS_PER_400_YEARS) * 400
    remaining = game_date % _DAYS_PER_400_YEARS

    while True:
        days_in_year = 366 if is_leap_year(year) else 365
        if remaining < days_in_year:
            return year
        remaining -= days_in_year
        year += 1


def year_to_game_date(year: int) -> int:
    """Return the game_date of 1 January in ``year``.

    Lets a game-date deadline be compared as a day count, avoiding a per-check
    year conversion.
    """
    if year <= 0:
        return 0

    full_cycles = year // 400
    game_date = full_cycles * _DAYS_PER_400_YEARS
    for y in range(full_cycles * 400, year):
        game_date += 366 if is_leap_year(y) else 365
    return game_date
