"""The health rules, against the shapes real runs actually failed in.

Every case here is taken from a session that happened. The four T1 runs of 2026-08-11
between them tripped no-vehicles, not-acting and stations-not-served, and every one of
those runs looked fine in its own log.
"""

from __future__ import annotations

from typing import Any

from nttd.monitor.health import (
    BARREN_STEPS,
    IDLE_FLEET_STEPS,
    SAME_REFUSAL_LIMIT,
    STALL_SECONDS,
    Health,
)


def _meta(**overrides: Any) -> dict[str, Any]:
    base = {
        "session_id": "ses_test",
        "live": False,
        "balance": 90_000,
        "stations": 2,
        "vehicles": 1,
        "actions": 20,
    }
    base.update(overrides)
    return base


def _steps(count: int) -> list[dict[str, Any]]:
    return [{"step": i} for i in range(count)]


def _rules(health: Health) -> list[str]:
    return [v["rule"] for v in health.verdicts()]


def test_a_working_run_trips_nothing() -> None:
    health = Health(_meta(), _steps(20), actions=[])
    assert health.verdicts() == []
    assert health.level() == "ok"
    assert health.summary() == "healthy"


def test_stations_without_vehicles_is_the_road_run_failure() -> None:
    """road-t1: 22 stations, 24 successful builds, no vehicle, 31 steps, rating 30."""
    health = Health(
        _meta(stations=22, vehicles=0, actions=24), _steps(31), actions=[],
    )
    assert "no vehicles" in _rules(health)
    assert health.level() == "bad"


def test_no_vehicles_is_not_reported_before_there_was_time_to_buy_one() -> None:
    """Building before buying is correct play, so the rule has to wait."""
    health = Health(
        _meta(stations=2, vehicles=0), _steps(IDLE_FLEET_STEPS - 1), actions=[],
    )
    assert "no vehicles" not in _rules(health)


def test_barely_acting_is_the_rail_run_failure() -> None:
    """rail-t1: 2 actions across 28 steps, blind to where its own stations were."""
    health = Health(
        _meta(stations=2, vehicles=0, actions=2), _steps(28), actions=[],
    )
    assert "not acting" in _rules(health)


def test_nothing_built_is_reported_once_there_has_been_time() -> None:
    health = Health(_meta(stations=0, vehicles=0), _steps(BARREN_STEPS), actions=[])
    assert "nothing built" in _rules(health)


def test_nothing_built_is_quiet_early_on() -> None:
    health = Health(_meta(stations=0, vehicles=0), _steps(BARREN_STEPS - 1), actions=[])
    assert "nothing built" not in _rules(health)


def test_a_repeated_refusal_is_a_loop_and_a_single_one_is_not() -> None:
    once = [{"action_type": "get_hangars", "status": "rejected"}]
    looping = once * SAME_REFUSAL_LIMIT
    assert "refusal loop" not in _rules(Health(_meta(), _steps(20), once))
    assert "refusal loop" in _rules(Health(_meta(), _steps(20), looping))


def test_only_a_live_session_can_stall() -> None:
    """An ended session is silent forever, and that is not a fault."""
    old = STALL_SECONDS + 60
    assert "stalled" not in _rules(
        Health(_meta(live=False), _steps(20), [], age_seconds=old),
    )
    assert "stalled" in _rules(
        Health(_meta(live=True), _steps(20), [], age_seconds=old),
    )


def test_a_slow_step_is_not_a_stall() -> None:
    health = Health(
        _meta(live=True), _steps(20), [], age_seconds=STALL_SECONDS - 1,
    )
    assert "stalled" not in _rules(health)


def test_an_overdrawn_balance_is_reported() -> None:
    assert "overdrawn" in _rules(Health(_meta(balance=-500), _steps(20), []))


def test_the_worst_level_wins_the_summary() -> None:
    """A bad rule and a warning together must not report as a warning."""
    health = Health(
        _meta(stations=22, vehicles=0, actions=24), _steps(31), actions=[],
    )
    rules = health.verdicts()
    assert rules[0]["level"] == "bad"
    assert health.level() == "bad"


def test_every_verdict_says_why_it_matters() -> None:
    """A verdict an operator cannot act on belongs in the report, not in health."""
    health = Health(
        _meta(stations=0, vehicles=0, actions=1, balance=-1, live=True),
        _steps(30),
        [{"action_type": "buy_vehicle", "status": "failed"}] * SAME_REFUSAL_LIMIT,
        age_seconds=STALL_SECONDS + 1,
    )
    verdicts = health.verdicts()
    assert len(verdicts) >= 4
    for verdict in verdicts:
        assert verdict["why_it_matters"].strip()
        assert verdict["detail"].strip()
        assert verdict["level"] in ("warn", "bad")
