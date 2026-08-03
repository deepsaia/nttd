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
    config = _agent(poll_interval=0.5, max_actions_per_cycle=50, observation_mode="full")
    limits = FairnessConfig(
        poll_interval=10.0, max_actions_per_cycle=15,
        observation_mode="compact", enforced=True,
    )

    changed = limits.apply_to(config)

    assert config.poll_interval == 10.0
    assert config.max_actions_per_cycle == 15
    assert config.observation_mode == "compact"
    assert len(changed) == 3, "each override is reported"


def test_unenforced_config_leaves_contestant_values_alone() -> None:
    """Scenario authoring and local experiments need the knobs."""
    config = _agent(poll_interval=0.5, max_actions_per_cycle=50)
    limits = FairnessConfig(poll_interval=10.0, max_actions_per_cycle=15, enforced=False)

    assert limits.apply_to(config) == []
    assert config.poll_interval == 0.5
    assert config.max_actions_per_cycle == 50


def test_matching_values_are_not_reported_as_changes() -> None:
    """A contestant who already asked for the limit changed nothing."""
    config = _agent(poll_interval=10.0, max_actions_per_cycle=15, max_history_cycles=10)
    limits = FairnessConfig(
        poll_interval=10.0, max_actions_per_cycle=15,
        max_history_cycles=10, observation_mode="compact", enforced=True,
    )
    assert limits.apply_to(config) == []


def test_change_report_names_the_old_and_new_value() -> None:
    """An operator needs to see what a contestant asked for versus what applied."""
    config = _agent(poll_interval=0.5)
    changed = FairnessConfig(poll_interval=10.0, enforced=True).apply_to(config)

    poll_change = next(c for c in changed if c.startswith("poll_interval"))
    assert "0.5" in poll_change
    assert "10.0" in poll_change


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
        "_fair_observation_mode": "full",
    })
    assert limits.poll_interval == 7.5
    assert limits.max_actions_per_cycle == 20
    assert limits.max_history_cycles == 3
    assert limits.llm_timeout_seconds == 45.0
    assert limits.observation_mode == "full"


def test_absent_settings_use_defaults() -> None:
    limits = from_settings({})
    assert limits.poll_interval == 10.0
    assert limits.max_actions_per_cycle == 15
    assert limits.llm_timeout_seconds == 120.0
    assert limits.observation_mode == "compact"


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
