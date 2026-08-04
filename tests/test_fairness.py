"""Tests for operator-owned fairness limits.

These parameters decide how much a contestant may do, so a contestant must not be
able to set them. They were once fields on the agent config an agent supplied at
registration, so every contestant was choosing their own budget: poll_interval has
a floor of 0.5s, and the bundled configs shipped max_actions_per_cycle as 5, 10,
and 50.

A scored session overrides them from the scenario. An unscored one leaves them
alone, because local experimentation needs the knobs.

Run with: uv run pytest tests/test_fairness.py -v
"""

from __future__ import annotations

from nttd.config.fairness import FairnessConfig, from_settings


def test_settings_are_parsed_into_limits() -> None:
    limits = from_settings({
        "_scored": "1",
        "_fair_poll_interval": "7.5",
        "_fair_max_actions": "20",
        "_fair_max_history": "3",
        "_fair_llm_timeout": "45.0",
        "_fair_observation_mode": "minimal",
    })
    assert limits.poll_interval == 7.5
    assert limits.max_actions_per_cycle == 20
    assert limits.max_history_cycles == 3
    assert limits.llm_timeout_seconds == 45.0
    # A scored run always observes fully: the scenario asked for "minimal" and does
    # not get it, because filtering is the agent's job and pinning a narrower class
    # would make two runs in a tier incomparable on information.
    assert limits.observation_mode == "full"


def test_absent_settings_use_defaults() -> None:
    limits = from_settings({})
    assert limits.poll_interval == 10.0
    assert limits.max_actions_per_cycle == 15
    assert limits.llm_timeout_seconds == 120.0
    assert limits.observation_mode == "full"


def test_malformed_settings_fall_back_rather_than_crash() -> None:
    """A bad value must not take down session start; it is logged and ignored."""
    limits = from_settings({
        "_fair_poll_interval": "not-a-number",
        "_fair_max_actions": "",
    })
    assert limits.poll_interval == 10.0
    assert limits.max_actions_per_cycle == 15


def test_as_dict_is_recordable() -> None:
    """The effective limits go into result.parquet, so they must serialise."""
    import json

    payload = json.loads(json.dumps(FairnessConfig(enforced=True).as_dict()))
    assert payload["enforced"] is True
    assert payload["poll_interval"] == 10.0


# ---------------------------------------------------------------------------
# The defaults themselves
# ---------------------------------------------------------------------------


def test_default_poll_interval_exceeds_the_slowest_measured_decide() -> None:
    """poll_interval is a PERIOD, so it only paces agents if it exceeds their
    decide time. The slowest measured role is rail at ~11.2s
    (docs/rail_agent_report.md), which the 10.0s default does NOT cover.

    This is deliberate and documented rather than accidental: raising the default
    above the slowest role would slow every other role for the sake of one. The
    test pins the relationship so a future change is a decision, not a drift.
    """
    limits = FairnessConfig()
    slowest_measured_decide = 11.242
    assert limits.poll_interval < slowest_measured_decide, (
        "if this now passes, the default was raised above the slowest decide time "
        "and every role is fully paced -- update this test deliberately"
    )


def test_default_max_actions_allows_a_complete_route() -> None:
    """A route needs loan, two stations, a connection, a vehicle, and orders."""
    assert FairnessConfig().max_actions_per_cycle >= 6


# ---------------------------------------------------------------------------
# Regressions found by review
# ---------------------------------------------------------------------------


def test_a_nonsensical_value_cannot_reach_the_action_budget() -> None:
    """Was: apply_to bypassed pydantic constraints via setattr, so an out-of-range
    scenario value was imposed on an agent config.

    apply_to is gone with the server-driven gameloop, but the underlying risk moved
    rather than vanished: the budget is now built straight from these limits, and a
    negative poll_interval would give a zero-length window -- a budget that refuses
    nothing. Clamping is what stops that, so this asserts it at the new boundary.
    """
    from nttd.runtime.action_budget import from_fairness

    limits = from_settings({"_fair_poll_interval": "-5.0", "_scored": "1"})
    assert limits.poll_interval >= 0.5, "a negative interval must be clamped"

    budget = from_fairness(limits)
    assert budget.window_seconds >= 0.5
    assert budget.enforced is True


def test_llm_timeout_only_applies_to_a_scored_session() -> None:
    """The other four limits respect `enforced`; this one used to be read straight
    off runtime.fairness, so a scenario cap leaked into unscored local runs.
    """
    unscored = from_settings({"_fair_llm_timeout": "5.0"})
    assert unscored.enforced is False

    scored = from_settings({"_scored": "1", "_fair_llm_timeout": "5.0"})
    assert scored.enforced is True
    assert scored.llm_timeout_seconds == 5.0


def test_scored_run_always_observes_fully() -> None:
    """Observation is deliberately NOT bounded.

    A scored run hands over the complete entitled game state and the agent decides
    what matters, because filtering is part of the task. A scenario cannot narrow it:
    doing so would make two runs in the same tier incomparable on information while
    appearing comparable, and would not stop an agent pulling the same data through
    observation tools anyway.
    """
    limits = from_settings({"_scored": "1", "_fair_observation_mode": "minimal"})
    assert limits.observation_mode == "full"


def test_out_of_range_values_are_clamped_not_used_verbatim() -> None:
    """The lenient config path only warns, then emitted the raw value.

    Unclamped, poll_interval = 0.0 gave a sleepless loop and max_history_cycles = -1
    raised ValueError from collections.deque(maxlen=-1) at registration.
    """
    limits = from_settings({
        "_scored": "1",
        "_fair_poll_interval": "0.0",
        "_fair_max_actions": "500",
        "_fair_max_history": "-1",
        "_fair_llm_timeout": "0.1",
    })
    assert limits.poll_interval == 0.5
    assert limits.max_actions_per_cycle == 200
    assert limits.max_history_cycles == 0
    assert limits.llm_timeout_seconds == 1.0


def test_clamped_history_is_usable_as_a_deque_maxlen() -> None:
    """The concrete failure clamping prevents."""
    import collections

    limits = from_settings({"_fair_max_history": "-1"})
    collections.deque(maxlen=limits.max_history_cycles)
