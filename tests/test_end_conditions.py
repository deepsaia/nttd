"""Tests for end conditions and the scored clock.

Three fairness properties are pinned here:

  * The wall-clock budget starts when a contestant first acts, not when the
    session was provisioned. Map generation and tile capture take a variable
    amount of time, so charging them would give two contestants on the same
    scenario different amounts of playing time.
  * The game-year deadline uses a leap-aware conversion. The naive
    ``game_date // 365 + 1`` is wrong by 2-3 years at OpenTTD's usual start
    dates, so a run scored "until 1970" would stop at the wrong year.
  * A bankrupt company ends the run instead of burning the remaining budget.

Run with: uv run pytest tests/test_end_conditions.py -v
"""

from __future__ import annotations

import time

from nttd.config.scenario_config import (
    BankruptcyConfig,
    EndConditionsConfig,
    GameDateLimitConfig,
    MaxHeartbeatsConfig,
    TimeLimitConfig,
)
from nttd.runtime.end_conditions import EndConditionChecker
from nttd.schemas.company import Company
from nttd.schemas.game import GameState
from nttd.schemas.snapshot import StateSnapshot
from nttd.utils.game_date import game_date_to_year, year_to_game_date


def _snapshot(game_date: int = 715_875, companies: list[Company] | None = None) -> StateSnapshot:
    return StateSnapshot(
        game=GameState(game_date=game_date),
        companies=companies if companies is not None else [Company(id=0, name="AgentCorp")],
    )


# ---------------------------------------------------------------------------
# Scored clock
# ---------------------------------------------------------------------------


def test_clock_does_not_start_at_construction() -> None:
    """Provisioning time must not be charged to the contestant."""
    checker = EndConditionChecker(
        EndConditionsConfig(time_limit=TimeLimitConfig(enabled=True, wall_minutes=0.0))
    )
    assert checker.clock_started is False

    # A zero-minute limit would fire immediately if the clock were already running.
    assert checker.check(_snapshot()).triggered is False


def test_limit_fires_once_the_clock_starts() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(time_limit=TimeLimitConfig(enabled=True, wall_minutes=0.0))
    )
    assert checker.start_clock(game_date=715_875) is True
    assert checker.clock_started is True

    result = checker.check(_snapshot())
    assert result.triggered is True
    assert "Time limit" in result.reason


def test_start_clock_is_idempotent() -> None:
    """Every action path calls it, so repeat calls must not restart the budget."""
    checker = EndConditionChecker(EndConditionsConfig(time_limit=TimeLimitConfig(enabled=False)))
    assert checker.start_clock(game_date=100) is True
    first = checker.start_time

    time.sleep(0.01)
    assert checker.start_clock(game_date=999) is False
    assert checker.start_time == first
    assert checker.start_game_date == 100, "the original start date is kept"


def test_explicit_start_time_is_honoured() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(time_limit=TimeLimitConfig(enabled=True, wall_minutes=0.0)),
        start_time=time.time() - 600,
    )
    assert checker.clock_started is True
    assert checker.check(_snapshot()).triggered is True


def test_reset_stops_the_clock() -> None:
    """Reset returns the checker to 'not started', ready for a new episode."""
    checker = EndConditionChecker(EndConditionsConfig(time_limit=TimeLimitConfig(enabled=False)))
    checker.start_clock(game_date=10)
    checker.reset()
    assert checker.clock_started is False
    assert checker.start_game_date is None


# ---------------------------------------------------------------------------
# Game-date deadline
# ---------------------------------------------------------------------------


def test_game_year_uses_leap_aware_conversion() -> None:
    """The naive date // 365 + 1 would report 1963 for a date in 1960."""
    date_in_1960 = 716_232
    assert game_date_to_year(date_in_1960) == 1960
    assert date_in_1960 // 365 + 1 == 1963, "documents the bug being guarded against"


def test_year_deadline_does_not_fire_early() -> None:
    """A 1970 deadline must not trigger during 1960, as the naive form would."""
    checker = EndConditionChecker(
        EndConditionsConfig(
            time_limit=TimeLimitConfig(enabled=False),
            game_date_limit=GameDateLimitConfig(enabled=True, end_year=1970),
        )
    )
    assert checker.check(_snapshot(game_date=716_232)).triggered is False


def test_year_deadline_fires_at_the_right_year() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(
            time_limit=TimeLimitConfig(enabled=False),
            game_date_limit=GameDateLimitConfig(enabled=True, end_year=1970),
        )
    )
    result = checker.check(_snapshot(game_date=year_to_game_date(1970)))
    assert result.triggered is True
    assert "1970" in result.reason


def test_year_round_trip() -> None:
    for year in (1, 400, 1950, 1960, 2000, 2050):
        assert game_date_to_year(year_to_game_date(year)) == year


# ---------------------------------------------------------------------------
# Bankruptcy
# ---------------------------------------------------------------------------


def test_bankruptcy_ends_the_run() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(
            time_limit=TimeLimitConfig(enabled=False),
            bankruptcy=BankruptcyConfig(enabled=True),
        )
    )
    result = checker.check(_snapshot(companies=[Company(id=0, name="Bust", is_active=False)]))
    assert result.triggered is True
    assert "no longer active" in result.reason


def test_bankruptcy_ignores_active_companies() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(
            time_limit=TimeLimitConfig(enabled=False),
            bankruptcy=BankruptcyConfig(enabled=True),
        )
    )
    assert checker.check(_snapshot()).triggered is False


def test_bankruptcy_disabled_by_default() -> None:
    """Opt-in: some scenarios legitimately let a company fail and continue."""
    checker = EndConditionChecker(EndConditionsConfig(time_limit=TimeLimitConfig(enabled=False)))
    assert checker.check(_snapshot(companies=[Company(id=0, is_active=False)])).triggered is False


# ---------------------------------------------------------------------------
# Step budget and combination logic
# ---------------------------------------------------------------------------


def test_max_heartbeats_counts_steps() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(
            time_limit=TimeLimitConfig(enabled=False),
            max_heartbeats=MaxHeartbeatsConfig(enabled=True, count=3),
        )
    )
    assert checker.check(_snapshot()).triggered is False
    assert checker.check(_snapshot()).triggered is False
    result = checker.check(_snapshot())
    assert result.triggered is True
    assert "Max heartbeats" in result.reason


def test_logic_all_requires_every_enabled_condition() -> None:
    checker = EndConditionChecker(
        EndConditionsConfig(
            logic="all",
            time_limit=TimeLimitConfig(enabled=True, wall_minutes=0.0),
            bankruptcy=BankruptcyConfig(enabled=True),
        )
    )
    checker.start_clock(game_date=0)

    # Time limit alone is met; bankruptcy is not.
    assert checker.check(_snapshot()).triggered is False

    # Both met.
    assert checker.check(_snapshot(companies=[Company(id=0, is_active=False)])).triggered is True


def test_no_conditions_never_triggers() -> None:
    checker = EndConditionChecker(EndConditionsConfig(time_limit=TimeLimitConfig(enabled=False)))
    for _ in range(5):
        assert checker.check(_snapshot()).triggered is False
