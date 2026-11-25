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


def test_the_world_carries_it_where_an_agent_reads_it() -> None:
    """On world.game, not on the snapshot handed to the checker.

    A full observation is built fresh from the world each time it is asked for, so a value
    set on that transient snapshot is gone by the time an agent reads it. That was the first
    attempt, and every observation reported a horizon of zero.
    """
    import inspect

    from nttd.runtime.orchestrator import Orchestrator

    source = inspect.getsource(Orchestrator._publish_horizon)
    assert "self.world.game.game_days_remaining" in source
    assert "self.world.game.game_days_total" in source


def test_a_run_not_bounded_by_days_reports_zero_rather_than_a_guess() -> None:
    """Zero total is "not measured in days", which is different from "none left"."""
    config = EndConditionsConfig()
    config.max_heartbeats = MaxHeartbeatsConfig(enabled=False, count=366)
    checker = EndConditionChecker(config)

    assert checker.game_days_total == 0
    assert checker.game_days_remaining == 0


def test_realtime_remaining_days_use_the_scored_duration(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from nttd.config.scenario_config import TimeLimitConfig
    from nttd.runtime.orchestrator import _SECS_PER_GAME_DAY, Orchestrator
    from nttd.state.world import WorldState

    now = [1000.0]
    monkeypatch.setattr("nttd.runtime.end_conditions.time.time", lambda: now[0])
    orchestrator = Orchestrator(WorldState(), MagicMock())
    orchestrator.configure_end_conditions(EndConditionsConfig(
        time_limit=TimeLimitConfig(enabled=True, wall_minutes=12),
        max_heartbeats=MaxHeartbeatsConfig(enabled=False),
    ))
    total = round(720 / _SECS_PER_GAME_DAY)
    game = orchestrator.world.snapshot().game
    assert game.game_days_total == game.game_days_remaining == game.episode_days == total

    # Provisioning time must not consume the game budget.
    now[0] += 500
    orchestrator._publish_horizon()
    assert orchestrator.world.snapshot().game.game_days_remaining == total
    orchestrator.start_scored_clock()

    now[0] += 360
    orchestrator._end_checker.check(orchestrator.world.snapshot())
    orchestrator._publish_horizon()
    assert orchestrator.world.snapshot().game.game_days_remaining == 183
    assert orchestrator.world.game.game_days_total == total

    # A partial final day is not reported as an already-finished episode.
    now[0] += 359.9
    orchestrator._publish_horizon()
    assert orchestrator.world.snapshot().game.game_days_remaining == 1
    now[0] += 0.1
    orchestrator._publish_horizon()
    assert orchestrator.world.snapshot().game.game_days_remaining == 0
    now[0] += 100
    orchestrator._publish_horizon()
    assert orchestrator.world.snapshot().game.game_days_remaining == 0


def test_remaining_days_respect_the_game_days_per_interval() -> None:
    from nttd.config.scenario_config import TimeLimitConfig
    from nttd.schemas.snapshot import StateSnapshot

    checker = EndConditionChecker(EndConditionsConfig(
        time_limit=TimeLimitConfig(enabled=False),
        max_heartbeats=MaxHeartbeatsConfig(enabled=True, count=10),
    ))
    assert checker.remaining_episode_days(3, 2.0) == 30
    for _ in range(3):
        checker.check(StateSnapshot())
    assert checker.remaining_episode_days(3, 2.0) == 21


def test_remaining_days_combine_enabled_limits_like_the_total(monkeypatch) -> None:
    from nttd.config.scenario_config import TimeLimitConfig
    from nttd.schemas.snapshot import StateSnapshot

    monkeypatch.setattr("nttd.runtime.end_conditions.time.time", lambda: 1060.0)
    for logic, expected in [("any", 27), ("all", 330)]:
        checker = EndConditionChecker(EndConditionsConfig(
            logic=logic,
            time_limit=TimeLimitConfig(enabled=True, wall_minutes=12),
            max_heartbeats=MaxHeartbeatsConfig(enabled=True, count=10),
        ), start_time=1000.0)
        checker.check(StateSnapshot())
        assert checker.remaining_episode_days(3, 2.0) == expected


def test_remaining_days_without_a_duration_bound_keep_the_existing_zero() -> None:
    from nttd.config.scenario_config import TimeLimitConfig

    checker = EndConditionChecker(EndConditionsConfig(
        time_limit=TimeLimitConfig(enabled=False),
        max_heartbeats=MaxHeartbeatsConfig(enabled=False),
    ))
    assert checker.remaining_episode_days(1, 2.0) == 0
