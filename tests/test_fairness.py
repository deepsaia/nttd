"""Tests for operator-owned fairness limits.

These parameters decide how much a contestant may do, so a contestant must not be
able to set them. They arrived on AgentConfig, which an agent supplies at
registration, so every contestant was choosing their own budget: poll_interval has
a floor of 0.5s, and the bundled configs shipped max_actions_per_cycle as 5, 10,
and 50.

A scored session overrides them from the scenario. An unscored one leaves them
alone, because local experimentation needs the knobs.

Run with: uv run pytest tests/test_fairness.py -v
"""

from __future__ import annotations

from nttd.config.fairness import FairnessConfig, from_settings
from nttd.gameloop.schemas import AgentConfig


def _agent(**kwargs: object) -> AgentConfig:
    base: dict = {"agent_id": "a1", "company_id": 0}
    base.update(kwargs)
    return AgentConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def test_enforced_config_overrides_contestant_values() -> None:
    """The core property: the scenario decides, not the contestant."""
    config = _agent(poll_interval=0.5, max_actions_per_cycle=50, observation_mode="minimal")
    limits = FairnessConfig(
        poll_interval=10.0, max_actions_per_cycle=15,
        observation_mode="full", enforced=True,
    )

    changed = limits.apply_to(config)

    assert config.poll_interval == 10.0
    assert config.max_actions_per_cycle == 15
    assert config.observation_mode == "full"
    assert len(changed) == 3, "each override is reported"
    # The requested value is retained: after the mutation it exists nowhere else,
    # so the record could not otherwise show what the contestant asked for.
    assert changed["poll_interval"] == (0.5, 10.0)


def test_unenforced_config_leaves_contestant_values_alone() -> None:
    """Scenario authoring and local experiments need the knobs."""
    config = _agent(poll_interval=0.5, max_actions_per_cycle=50)
    limits = FairnessConfig(poll_interval=10.0, max_actions_per_cycle=15, enforced=False)

    assert limits.apply_to(config) == {}
    assert config.poll_interval == 0.5
    assert config.max_actions_per_cycle == 50


def test_matching_values_are_not_reported_as_changes() -> None:
    """A contestant who already asked for the limit changed nothing."""
    config = _agent(
        poll_interval=10.0, max_actions_per_cycle=15,
        max_history_cycles=10, observation_mode="full",
    )
    limits = FairnessConfig(
        poll_interval=10.0, max_actions_per_cycle=15,
        max_history_cycles=10, observation_mode="full", enforced=True,
    )
    assert limits.apply_to(config) == {}


def test_change_report_names_the_old_and_new_value() -> None:
    """An operator needs to see what a contestant asked for versus what applied."""
    config = _agent(poll_interval=0.5)
    changed = FairnessConfig(poll_interval=10.0, enforced=True).apply_to(config)

    assert changed["poll_interval"] == (0.5, 10.0)


# ---------------------------------------------------------------------------
# Construction from settings
# ---------------------------------------------------------------------------


def test_enforcement_follows_the_scored_flag() -> None:
    """A scored run must be bounded by its task; an unscored one has nothing to
    protect, so there is no separate switch to forget to set.
    """
    assert from_settings({"_scored": "1"}).enforced is True
    assert from_settings({}).enforced is False
    assert from_settings({"_scored": "0"}).enforced is False


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


def test_out_of_range_override_is_rejected_not_silently_applied() -> None:
    """apply_to writes via setattr, which bypasses field constraints unless the
    model validates on assignment. A scenario with a nonsensical value must fail
    loudly rather than impose it.
    """
    import pytest
    from pydantic import ValidationError

    config = _agent()
    with pytest.raises(ValidationError):
        FairnessConfig(poll_interval=-5.0, enforced=True).apply_to(config)


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
