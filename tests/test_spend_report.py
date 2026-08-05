"""Contestant-reported spend, per model.

nttd runs no agent, so it cannot observe a model name, a token count, or a cost.
Those columns in result.parquet were permanently empty: ParticipantReport existed to
hold them and nothing ever filled it, because the reporting endpoint was never built.

Spend is per MODEL rather than a single figure. A multi-agent system routinely uses
several -- neuro-san runs a front-man plus specialists, often on different models --
so a cheap router in front of one expensive planner is a different system from the
same total spent uniformly, and one string cannot say which.

Run with: uv run pytest tests/test_spend_report.py -v
"""

from __future__ import annotations

from nttd.runtime.participant_report import ParticipantReport
from nttd.schemas.spend_report import ModelSpend, SpendReport


def _report() -> ParticipantReport:
    return ParticipantReport()


# ---------------------------------------------------------------------------
# Observed versus reported
# ---------------------------------------------------------------------------


def test_action_counts_come_from_nttd_not_the_contestant() -> None:
    """The observed half: a contestant cannot inflate these without submitting the
    actions, and submitting them means passing the budget and the allowlist."""
    report = _report()
    summary = report.build(action_counts={0: {"total_actions": 42, "successful_actions": 40}})
    assert summary[0]["total_actions"] == 42
    assert summary[0]["successful_actions"] == 40


def test_a_contestant_that_reports_nothing_still_gets_a_row() -> None:
    """The observed half comes from nttd's records, not the contestant's cooperation."""
    summary = _report().build(action_counts={0: {"total_actions": 3, "successful_actions": 3}})
    assert summary[0]["total_actions"] == 3
    assert summary[0]["spend_is_reported"] is False


def test_silence_is_distinguishable_from_a_reported_zero() -> None:
    """A local RL policy that genuinely cost nothing and a MAS entry that stayed
    silent both show 0.0, so the flag is what tells them apart."""
    silent = _report().build(action_counts={0: {}})
    assert silent[0]["total_cost"] == 0.0
    assert silent[0]["spend_is_reported"] is False

    free = _report()
    free.declare(0, models=[ModelSpend(model="local-ppo", total_cost_usd=0.0)])
    reported = free.build()
    assert reported[0]["total_cost"] == 0.0
    assert reported[0]["spend_is_reported"] is True


# ---------------------------------------------------------------------------
# Several models in one system
# ---------------------------------------------------------------------------


def test_each_model_is_kept_separately() -> None:
    """The neuro-san shape: a cheap front-man plus expensive specialists."""
    report = _report()
    report.declare(0, models=[
        ModelSpend(model="claude-haiku-4.5", role="front_man",
                   prompt_tokens=8000, completion_tokens=600, total_cost_usd=0.012),
        ModelSpend(model="claude-opus-5", role="route_planner",
                   prompt_tokens=40000, completion_tokens=3000, total_cost_usd=1.85),
    ])
    breakdown = report.model_breakdown(0)
    assert len(breakdown) == 2
    assert {entry["model"] for entry in breakdown} == {
        "claude-haiku-4.5", "claude-opus-5",
    }


def test_the_same_model_in_two_roles_stays_separate() -> None:
    """Role is part of the key: running one model as both planner and validator is a
    real topology, and collapsing them would hide where the spend went."""
    report = _report()
    report.declare(0, models=[
        ModelSpend(model="gpt-5.2", role="planner", total_cost_usd=1.0),
        ModelSpend(model="gpt-5.2", role="validator", total_cost_usd=0.25),
    ])
    assert len(report.model_breakdown(0)) == 2


def test_repeated_reports_accumulate_rather_than_replace() -> None:
    """So a loop can report each cycle's usage as its provider returns it, instead of
    accumulating totals itself."""
    report = _report()
    for _ in range(3):
        report.declare(0, models=[
            ModelSpend(model="claude-opus-5", prompt_tokens=1000, total_cost_usd=0.5),
        ])
    entry = report.model_breakdown(0)[0]
    assert entry["prompt_tokens"] == 3000
    assert entry["total_cost_usd"] == 1.5


def test_totals_are_rolled_up_for_the_result_row() -> None:
    report = _report()
    report.declare(0, models=[
        ModelSpend(model="a", prompt_tokens=10, completion_tokens=1, total_cost_usd=0.1),
        ModelSpend(model="b", prompt_tokens=20, completion_tokens=2, total_cost_usd=0.2),
    ])
    summary = report.build()[0]
    assert summary["prompt_tokens"] == 30
    assert summary["completion_tokens"] == 3
    assert summary["total_cost"] == 0.3


def test_the_model_column_names_every_model_that_ran() -> None:
    """A single column still has to say something, and the honest summary of a
    multi-model system is all of them rather than the first or the priciest."""
    report = _report()
    report.declare(0, models=[
        ModelSpend(model="gpt-5.2"), ModelSpend(model="claude-opus-5"),
    ])
    assert report.build()[0]["model"] == "claude-opus-5+gpt-5.2"


# ---------------------------------------------------------------------------
# Identity, and robustness
# ---------------------------------------------------------------------------


def test_identity_fields_are_replaced_not_accumulated() -> None:
    report = _report()
    report.declare(0, nttd_framework="langchain")
    report.declare(0, nttd_framework="neuro-san")
    assert report.build()[0]["nttd_framework"] == "neuro-san"


def test_spend_is_tracked_per_company() -> None:
    """Two contestants must not pool their costs."""
    report = _report()
    report.declare(0, models=[ModelSpend(model="a", total_cost_usd=1.0)])
    report.declare(1, models=[ModelSpend(model="b", total_cost_usd=2.0)])
    summary = report.build()
    assert summary[0]["total_cost"] == 1.0
    assert summary[1]["total_cost"] == 2.0


def test_an_entry_with_no_model_name_is_ignored() -> None:
    """Rather than creating an unattributable bucket."""
    report = _report()
    report.declare(0, models=[{"model": "", "total_cost_usd": 5.0}])
    assert report.model_breakdown(0) == []


def test_a_non_numeric_value_does_not_break_the_report() -> None:
    """The audit path must not be able to fail the run it describes."""
    report = _report()
    report.declare(0, models=[
        {"model": "a", "prompt_tokens": "lots", "total_cost_usd": 1.0},
    ])
    entry = report.model_breakdown(0)[0]
    assert entry["prompt_tokens"] == 0
    assert entry["total_cost_usd"] == 1.0


def test_the_report_schema_defaults_to_empty() -> None:
    """Nothing is required: reporting is optional."""
    assert SpendReport().models == []
    assert SpendReport().nttd_framework == ""
