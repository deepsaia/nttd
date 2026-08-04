"""Tests for the per-company action ceiling on the submission path.

One rule: a single submit or batch may carry at most ``max_actions_per_decision``
actions. It applies to both modes, since a submission is variable-length in either --
real-time, whatever batch a contestant decided on; stepped, whatever it accumulated
while paused and flushes on stepping.

What is NOT here, and why, since both were built and removed:

  * A RATE limit. A sliding wall-clock window of N per interval allowed about 2,700
    actions in a 30-minute real-time run against about 900 for the same task played
    stepped, so it made the modes threefold incomparable while presenting itself as a
    fairness guarantee. It also bounded rhythm rather than work: idle nine seconds,
    burst fifteen, pass.
  * A TOTAL for the run. Stepped mode is already bounded by its step count, and how
    many of its 15 a policy spends per step is the policy's own optimisation problem
    -- which is what an RL or ES entry is being scored on.

Per company rather than per agent, because scoring is per company and several
contestant loops legitimately share one.

Run with: uv run pytest tests/test_action_budget.py -v
"""

from __future__ import annotations

from nttd.config.fairness import FairnessConfig
from nttd.runtime.action_budget import ActionBudget, from_fairness


def _budget(max_per_submission: int = 15, enforced: bool = True) -> ActionBudget:
    return ActionBudget(max_per_submission=max_per_submission, enforced=enforced)


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------


def test_a_submission_within_the_ceiling_is_allowed() -> None:
    assert _budget(15).check(company_id=0, count=15).allowed is True


def test_a_submission_over_the_ceiling_is_refused() -> None:
    decision = _budget(15).check(company_id=0, count=16)
    assert decision.allowed is False
    assert decision.limit == 15
    assert "exceeds the ceiling" in decision.reason


def test_the_refusal_says_how_to_proceed() -> None:
    """An agent that is only told "no" retries the same thing forever."""
    assert "split it" in _budget(5).check(company_id=0, count=50).reason


def test_repeated_submissions_are_not_cumulatively_capped() -> None:
    """Deliberate: there is no total for the run.

    A contestant may keep submitting; how much it chooses to do is part of what is
    being measured, and in stepped mode the step count already bounds the run.
    """
    budget = _budget(15)
    for _ in range(100):
        assert budget.check(company_id=0, count=15).allowed is True
        budget.consume(company_id=0, count=15)


def test_a_single_action_is_always_within_a_sane_ceiling() -> None:
    assert _budget(1).check(company_id=0, count=1).allowed is True


def test_a_zero_ceiling_disables_enforcement() -> None:
    """A scenario with no ceiling must not accidentally refuse everything."""
    assert ActionBudget(max_per_submission=0, enforced=True).check(0, count=99).allowed


# ---------------------------------------------------------------------------
# Per company, not per agent
# ---------------------------------------------------------------------------


def test_usage_is_tracked_per_company() -> None:
    budget = _budget(15)
    budget.consume(company_id=0, count=10)
    budget.consume(company_id=1, count=3)
    assert budget.usage()["used_actions"] == {"0": 10, "1": 3}


def test_one_company_refusal_does_not_affect_another() -> None:
    budget = _budget(5)
    assert budget.check(company_id=0, count=50).allowed is False
    assert budget.check(company_id=1, count=5).allowed is True


def test_loops_sharing_a_company_share_its_ceiling() -> None:
    """The multi-agent shape: several loops, one company, one ceiling.

    A per-loop ceiling would hand a 3-loop entry three times the actions of a
    single-loop entry on the same task.
    """
    budget = _budget(15)
    assert budget.check(company_id=0, count=16).allowed is False, (
        "a loop cannot exceed the company ceiling by submitting a bigger batch"
    )


# ---------------------------------------------------------------------------
# Unenforced behaviour
# ---------------------------------------------------------------------------


def test_unenforced_budget_allows_everything() -> None:
    """Local experimentation and scenario authoring are not limited."""
    assert _budget(1, enforced=False).check(company_id=0, count=500).allowed is True


def test_unenforced_budget_still_records_usage() -> None:
    """An unscored run should still report what a contestant did."""
    budget = _budget(1, enforced=False)
    budget.consume(company_id=0, count=7)
    usage = budget.usage()
    assert usage["enforced"] is False
    assert usage["used_actions"] == {"0": 7}
    assert usage["total_refused"] == 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_refusals_are_counted_per_company() -> None:
    budget = _budget(2)
    budget.check(company_id=0, count=10)
    budget.check(company_id=0, count=3)
    usage = budget.usage()
    assert usage["refused_actions"] == {"0": 13}
    assert usage["total_refused"] == 13


def test_usage_is_json_serialisable() -> None:
    """It goes into the result record."""
    import json

    budget = _budget(2)
    budget.consume(company_id=0, count=2)
    budget.check(company_id=0, count=9)
    assert json.loads(json.dumps(budget.usage()))["total_refused"] == 9


# ---------------------------------------------------------------------------
# Construction from the fairness limits
# ---------------------------------------------------------------------------


def test_the_budget_mirrors_the_fairness_ceiling() -> None:
    budget = from_fairness(FairnessConfig(max_actions_per_decision=20, enforced=True))
    assert budget.max_per_submission == 20
    assert budget.enforced is True


def test_unenforced_fairness_yields_an_unenforced_budget() -> None:
    budget = from_fairness(FairnessConfig(enforced=False))
    assert budget.enforced is False
    assert budget.check(company_id=0, count=1000).allowed is True


def test_no_window_or_total_fields_remain() -> None:
    """Guards against a rate limit or run total creeping back in."""
    usage = _budget().usage()
    for gone in ("window_seconds", "max_actions_per_window", "total_actions"):
        assert gone not in usage, f"{gone} is back; see the module docstring"
