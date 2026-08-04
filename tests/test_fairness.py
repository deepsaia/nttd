"""Tests for the operator-owned fairness limit.

One knob, ``max_actions_per_decision``: the ceiling on a single submission. A
contestant must not be able to set it, since it decides how much they may do -- it was
once a field on the agent config an agent supplied at registration, so every
contestant was choosing their own budget.

Three things it deliberately is not:

  * A RATE limit. There was one, a sliding wall-clock window, removed because at 15
    actions per 10s a 30-minute real-time run allowed about 2,700 actions against
    about 900 for the same task played stepped -- threefold incomparable, while
    presenting itself as a fairness guarantee.
  * A TOTAL for the run. Stepped mode is bounded by its step count; how many of the
    15 a policy spends per step is what an RL or ES entry is being scored on.
  * An LLM timeout or history depth. Both are client concerns and unenforceable.

Run with: uv run pytest tests/test_fairness.py -v
"""

from __future__ import annotations

from nttd.config.fairness import SCORED_OBSERVATION_MODE, FairnessConfig, from_settings


def test_enforcement_follows_the_scored_flag() -> None:
    """Tied to the session being scored rather than a separate switch: a scored run
    must be bounded by its task, and an unscored one has nothing to protect."""
    assert from_settings({"_scored": "1"}).enforced is True
    assert from_settings({}).enforced is False
    assert from_settings({"_scored": "0"}).enforced is False


def test_the_limit_comes_from_the_profile_not_the_session() -> None:
    """A scenario cannot set its own budget, so the value must not be readable from
    session settings. Passing one has no effect."""
    from nttd.config.benchmark_profile import active_profile

    expected = int(active_profile().fairness["max_actions_per_decision"])
    limits = from_settings({"_scored": "1", "_fair_max_actions": "200"})
    assert limits.max_actions_per_decision == expected


def test_the_default_allows_a_complete_route() -> None:
    """A route needs loan, two stations, a connection, a vehicle, and orders."""
    assert FairnessConfig().max_actions_per_decision >= 6


def test_a_scored_run_always_observes_fully() -> None:
    """Observation is deliberately NOT bounded.

    A scored run hands over the complete entitled game state and the contestant
    decides what matters, because filtering is part of the task. Narrowing it would
    make two runs in a tier incomparable on information while appearing comparable,
    and would not stop a contestant pulling the same data through queries anyway.
    """
    assert from_settings({"_scored": "1"}).observation_mode == "full"
    assert SCORED_OBSERVATION_MODE == "full"


def test_no_rate_or_timeout_fields_remain() -> None:
    """Guards against them creeping back.

    Each was removed for a stated reason: a wall-clock window made the two modes
    threefold incomparable, and an LLM timeout or history depth cannot be enforced
    against a loop running in the contestant's own process. Restating an
    unenforceable suggestion as a limit misleads a reader of the result.
    """
    fields = FairnessConfig().as_dict()
    for gone in (
        "poll_interval", "window_seconds", "realtime_window_seconds",
        "llm_timeout_seconds", "max_history_cycles", "max_actions_per_cycle",
        "total_actions",
    ):
        assert gone not in fields, f"{gone} is back; see the module docstring"


def test_as_dict_is_recordable() -> None:
    """The effective limit goes into result.parquet, so it must serialise."""
    import json

    payload = json.loads(json.dumps(FairnessConfig(enforced=True).as_dict()))
    assert payload["enforced"] is True
    assert payload["max_actions_per_decision"] == 15


def test_a_non_numeric_profile_value_falls_back_rather_than_crashing(
    monkeypatch: object,
) -> None:
    """A typo in operator policy must not take down session start."""
    from nttd.config import fairness as fairness_module
    from nttd.config.benchmark_profile import BenchmarkProfile

    broken = BenchmarkProfile(
        locked={}, allowed={}, fairness={"max_actions_per_decision": "many"},
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        fairness_module, "active_profile", lambda: broken,
    )
    assert from_settings({"_scored": "1"}).max_actions_per_decision == 15
