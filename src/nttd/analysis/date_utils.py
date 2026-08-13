"""Convert OpenTTD game dates (days since year 0) to human-readable strings."""

from __future__ import annotations

import polars as pl

_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or year % 400 == 0


def game_date_to_ymd(game_date: int) -> tuple[int, int, int]:
    """Convert an OpenTTD game_date to (year, month_1based, day_1based)."""
    year = 0
    remaining = game_date

    # Fast-forward by 400-year blocks (146097 days each)
    blocks_400 = remaining // 146097
    year += blocks_400 * 400
    remaining -= blocks_400 * 146097

    while True:
        days_in_year = 366 if _is_leap(year) else 365
        if remaining < days_in_year:
            break
        remaining -= days_in_year
        year += 1

    months = [31, 29 if _is_leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    month = 0
    for m_days in months:
        if remaining < m_days:
            break
        remaining -= m_days
        month += 1

    return year, month + 1, remaining + 1


def game_date_to_str(game_date: int) -> str:
    """Convert game_date to '5 Jan 1950' format."""
    year, month, day = game_date_to_ymd(game_date)
    return f"{day} {_MONTH_NAMES[month - 1]} {year}"


def game_date_to_dmy(game_date: int) -> str:
    """Convert game_date to '05-Jan-1950' format.

    Zero padded and hyphenated, for the action and event tables. Those columns used to show the
    raw day count, 737792, which is what OpenTTD reports and what nothing can read: two rows
    twelve days apart looked like two arbitrary large numbers.
    """
    year, month, day = game_date_to_ymd(game_date)
    return f"{day:02d}-{_MONTH_NAMES[month - 1]}-{year}"


def game_date_to_short(game_date: int) -> str:
    """Convert game_date to 'Jan 1950' format (month + year only)."""
    year, month, _ = game_date_to_ymd(game_date)
    return f"{_MONTH_NAMES[month - 1]} {year}"


def add_readable_dates(df: pl.DataFrame, col: str = "game_date") -> pl.DataFrame:
    """Add a 'date_str' column with human-readable dates derived from game_date."""
    if col not in df.columns:
        return df
    return df.with_columns(
        pl.col(col).map_elements(game_date_to_str, return_dtype=pl.Utf8).alias("date_str"),
    )
