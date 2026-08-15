"""A contestant can see how long the run is, because planning is impossible without it.

Whether to buy a vehicle depends on whether there is time for it to pay for itself: an
aircraft takes roughly 190 game days to return its price, so one bought with sixty days left
is cash converted into a depreciating asset. A run that hides its own horizon forces that
decision to be made blind.

It is written onto the game state as heartbeats are counted, rather than assembled in one
route, so the status endpoint, the full observation an agent plans against, and the snapshots
the monitor draws all report the same number.
"""

from __future__ import annotations

from nttd.config.scenario_config import EndConditionsConfig, MaxHeartbeatsConfig
from nttd.runtime.end_conditions import EndConditionChecker
from nttd.schemas.game import GameState


def _checker(count: int = 366) -> EndConditionChecker:
    config = EndConditionsConfig()
    config.max_heartbeats = MaxHeartbeatsConfig(enabled=True, count=count)
    return EndConditionChecker(config)


def test_the_budget_is_reported_before_anything_has_happened() -> None:
    checker = _checker(366)
    assert checker.game_days_total == 366
    assert checker.game_days_remaining == 366


def test_what_is_left_falls_as_the_run_proceeds() -> None:
    checker = _checker(10)

    class _Snapshot:
        game = GameState()
        companies: list = []
        vehicles: list = []
        stations: list = []

    snapshot = _Snapshot()
    for _ in range(3):
        checker.check(snapshot)

    assert checker.game_days_remaining == 7
    # And the world carries it, which is where an agent reads it from.
    assert snapshot.game.game_days_remaining == 7
    assert snapshot.game.game_days_total == 10


def test_a_run_not_bounded_by_days_reports_zero_rather_than_a_guess() -> None:
    """Zero total is "not measured in days", which is different from "none left"."""
    config = EndConditionsConfig()
    config.max_heartbeats = MaxHeartbeatsConfig(enabled=False, count=366)
    checker = EndConditionChecker(config)

    assert checker.game_days_total == 0
    assert checker.game_days_remaining == 0
