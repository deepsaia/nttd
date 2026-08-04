"""Per-company action budget: a ceiling on one submission.

A ceiling on how many actions one submission may carry: 15 by default, enough for a
route -- loan, two stations, a connection, a vehicle, orders -- with room to spare.

That is the whole rule, and it applies to both modes. A submission is variable-length
in either: real-time, a contestant posts whatever batch it has decided on; stepped, it
accumulates actions while paused and flushes them when it steps. The ceiling bounds
the batch; it does not dictate its size.

Two other bounds were tried and dropped:

  * A RATE limit, as a sliding wall-clock window of N actions per interval. At 15 per
    10s a 30-minute real-time run allowed about 2,700 actions against about 900 for
    the same task played stepped, so it made the two modes threefold incomparable
    while presenting itself as a fairness guarantee. It also bounded rhythm rather
    than work: an agent that idled nine seconds and burst fifteen passed, while one
    that paced evenly hit the same ceiling.

  * A TOTAL for the run. Stepped mode already has a natural denominator -- the step --
    and ``max_heartbeats`` bounds how many there are, so the run is bounded without
    one. How many of its 15 a policy actually spends per step is then the policy's own
    optimisation problem, which is exactly what an RL or ES entry is being scored on.
    Imposing a second total would score the platform's guess at the answer instead.

Per COMPANY rather than per agent, because scoring is per company and several
contestant loops legitimately share one. A per-loop ceiling would hand a 3-loop entry
three times the actions of a single-loop entry on the same task.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BudgetDecision:
    """Whether a submission is within budget, and why not if it is not."""

    allowed: bool
    reason: str = ""
    used: int = 0
    limit: int = 0


@dataclass
class ActionBudget:
    """Per-submission action ceiling, with usage tracked per company.

    Attributes:
        max_per_submission: Ceiling on a single submit or batch. 0 disables it.
        enforced: Whether to refuse. False records usage without blocking, so an
            unscored session still reports what a contestant did.
    """

    max_per_submission: int = 0
    enforced: bool = False
    _used: dict[int, int] = field(default_factory=lambda: defaultdict(int), repr=False)
    _refused: dict[int, int] = field(default_factory=lambda: defaultdict(int), repr=False)

    def check(self, company_id: int, count: int = 1) -> BudgetDecision:
        """Test whether a submission of ``count`` actions is permitted.

        Reads with ``.get`` rather than indexing: ``_used`` is a defaultdict, so
        indexing it here materialised the key and a company that only ever tried
        appeared in the usage report with a count of zero.
        """
        used = self._used.get(company_id, 0)
        if not self.enforced or self.max_per_submission <= 0:
            return BudgetDecision(allowed=True, used=used, limit=self.max_per_submission)

        if count > self.max_per_submission:
            self._refused[company_id] += count
            return BudgetDecision(
                allowed=False,
                reason=(
                    f"{count} actions in one submission exceeds the ceiling of "
                    f"{self.max_per_submission}; split it across decisions"
                ),
                used=used,
                limit=self.max_per_submission,
            )

        return BudgetDecision(allowed=True, used=used, limit=self.max_per_submission)

    def consume(self, company_id: int, count: int = 1) -> None:
        """Record ``count`` actions against a company.

        Recorded even when unenforced, so ``usage`` reflects what happened. Action
        counts also come from the recorder's own tally of actions.parquet; this one
        exists so the budget can report refusals alongside them.
        """
        self._used[company_id] += max(0, count)

    def usage(self) -> dict[str, object]:
        """Flatten for the result record."""
        return {
            "enforced": self.enforced,
            "max_per_submission": self.max_per_submission,
            "used_actions": {str(k): v for k, v in sorted(self._used.items())},
            "refused_actions": {str(k): v for k, v in sorted(self._refused.items())},
            "total_refused": sum(self._refused.values()),
        }


def from_fairness(fairness: object) -> ActionBudget:
    """Build a budget from the profile's fairness limits."""
    return ActionBudget(
        max_per_submission=int(getattr(fairness, "max_actions_per_decision", 0) or 0),
        enforced=bool(getattr(fairness, "enforced", False)),
    )
