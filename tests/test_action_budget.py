"""Tests for the per-company action budget on the REST path.

FairnessConfig binds at agent registration, so it only limited contestants who
drove the gameloop. A contestant posting straight to /actions/submit had no pacing
limit at all, and every bundled example uses that path -- so the budget bound almost
nobody. This enforces it where actions enter the server.

Per company rather than per agent because scoring is per company and several agents
legitimately share one.

Run with: uv run pytest tests/test_action_budget.py -v
"""

from __future__ import annotations

import time

from nttd.config.fairness import FairnessConfig
from nttd.runtime.action_budget import ActionBudget, from_fairness


def _budget(max_actions: int = 3, window: float = 60.0, enforced: bool = True) -> ActionBudget:
    return ActionBudget(max_actions=max_actions, window_seconds=window, enforced=enforced)


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def test_actions_within_budget_are_allowed() -> None:
    budget = _budget(max_actions=3)
    for _ in range(3):
        assert budget.check(company_id=0).allowed is True
        budget.consume(company_id=0)


def test_exceeding_the_budget_is_refused() -> None:
    budget = _budget(max_actions=2)
    for _ in range(2):
        budget.consume(company_id=0)

    decision = budget.check(company_id=0)
    assert decision.allowed is False
    assert decision.used == 2
    assert decision.limit == 2
    assert "exceed the scenario's budget" in decision.reason


def test_a_batch_larger_than_the_budget_is_refused_whole() -> None:
    """submit-batch and interpret accept lists, so the count matters, not just one."""
    budget = _budget(max_actions=5)
    assert budget.check(company_id=0, count=6).allowed is False
    assert budget.check(company_id=0, count=5).allowed is True


def test_budget_is_per_company_not_global() -> None:
    """Two contestants must not share one budget."""
    budget = _budget(max_actions=2)
    for _ in range(2):
        budget.consume(company_id=0)

    assert budget.check(company_id=0).allowed is False
    assert budget.check(company_id=1).allowed is True, "company 1 has its own budget"


def test_agents_sharing_a_company_share_its_budget() -> None:
    """The shipped 3-agent scenario puts road, air, and water all on company 0.

    A per-agent budget would give that entry three times the actions of a
    single-agent entry on the same scenario.
    """
    budget = _budget(max_actions=4)
    for _ in range(4):  # spread across three notional agents, one company
        budget.consume(company_id=0)

    assert budget.check(company_id=0).allowed is False


def test_window_slides_so_old_actions_stop_counting() -> None:
    budget = _budget(max_actions=2, window=0.05)
    for _ in range(2):
        budget.consume(company_id=0)
    assert budget.check(company_id=0).allowed is False

    time.sleep(0.06)
    assert budget.check(company_id=0).allowed is True, "the window has slid past"


# ---------------------------------------------------------------------------
# Unenforced behaviour
# ---------------------------------------------------------------------------


def test_unenforced_budget_allows_everything() -> None:
    """Local experimentation and scenario authoring are not rate limited."""
    budget = _budget(max_actions=1, enforced=False)
    for _ in range(50):
        assert budget.check(company_id=0).allowed is True
        budget.consume(company_id=0)


def test_unenforced_budget_still_records_usage() -> None:
    """An unscored run should still report what a contestant did."""
    budget = _budget(max_actions=1, enforced=False)
    for _ in range(5):
        budget.consume(company_id=0)

    assert budget.usage()["enforced"] is False
    assert budget.usage()["total_refused"] == 0


def test_zero_limit_disables_enforcement() -> None:
    """A scenario with no budget must not accidentally refuse everything."""
    assert ActionBudget(max_actions=0, window_seconds=10.0, enforced=True).check(0).allowed
    assert ActionBudget(max_actions=5, window_seconds=0.0, enforced=True).check(0).allowed


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_refusals_are_counted_per_company() -> None:
    budget = _budget(max_actions=1)
    budget.consume(company_id=0)
    budget.check(company_id=0)
    budget.check(company_id=0, count=3)

    usage = budget.usage()
    assert usage["refused_actions"] == {"0": 4}
    assert usage["total_refused"] == 4


def test_usage_is_json_serialisable() -> None:
    """It goes into the result record."""
    import json

    budget = _budget(max_actions=1)
    budget.consume(company_id=0)
    budget.check(company_id=0)
    assert json.loads(json.dumps(budget.usage()))["total_refused"] == 1


# ---------------------------------------------------------------------------
# Construction from the fairness config
# ---------------------------------------------------------------------------


def test_budget_mirrors_the_fairness_limits() -> None:
    """The REST path is held to the same rate a gameloop agent is."""
    budget = from_fairness(
        FairnessConfig(poll_interval=10.0, max_actions_per_cycle=15, enforced=True)
    )
    assert budget.max_actions == 15
    assert budget.window_seconds == 10.0
    assert budget.enforced is True


def test_unenforced_fairness_yields_an_unenforced_budget() -> None:
    budget = from_fairness(FairnessConfig(enforced=False))
    assert budget.enforced is False
    assert budget.check(company_id=0, count=1000).allowed is True


# ---------------------------------------------------------------------------
# The gameloop draws from the same company budget as the REST path
# ---------------------------------------------------------------------------


class _StubConnection:
    """Binds the real AgentConnection method to a stub, so the test exercises
    production logic rather than a copy of it."""

    def __init__(self, budget: ActionBudget, company_id: int, ceiling: int) -> None:
        from types import SimpleNamespace

        from nttd.gameloop.connection import AgentConnection

        self.runtime = SimpleNamespace(action_budget=budget)
        self.config = SimpleNamespace(
            company_id=company_id, max_actions_per_cycle=ceiling,
        )
        self._allowance = AgentConnection._company_action_allowance.__get__(self)


def test_allowance_shrinks_as_a_company_spends_its_budget() -> None:
    """Three agents on one company must share the ceiling, not each get it.

    The shipped 3-agent scenario puts road, air, and water all on company 0, so a
    per-agent ceiling handed that entry 3x the actions of a single-agent entry.
    """
    budget = _budget(max_actions=6)
    conn = _StubConnection(budget, company_id=0, ceiling=6)

    assert conn._allowance(4) == 4          # agent one takes its share
    budget.consume(0, 4)
    assert conn._allowance(4) == 2          # agent two gets what is left
    budget.consume(0, 2)
    assert conn._allowance(4) == 0          # agent three gets nothing


def test_allowance_is_independent_across_companies() -> None:
    budget = _budget(max_actions=3)
    budget.consume(0, 3)

    assert _StubConnection(budget, company_id=0, ceiling=3)._allowance(3) == 0
    assert _StubConnection(budget, company_id=1, ceiling=3)._allowance(3) == 3


def test_allowance_falls_back_to_the_agent_ceiling_when_unenforced() -> None:
    """An unscored run behaves as it did before, truncating per agent."""
    budget = _budget(max_actions=2, enforced=False)
    assert _StubConnection(budget, company_id=0, ceiling=5)._allowance(9) == 5


def test_allowance_never_exceeds_the_agent_ceiling() -> None:
    """The per-agent ceiling is still an upper bound, not just the company budget."""
    budget = _budget(max_actions=100)
    assert _StubConnection(budget, company_id=0, ceiling=5)._allowance(50) == 5
