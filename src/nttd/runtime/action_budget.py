"""Per-company action budget for the REST path.

``FairnessConfig`` binds at agent registration, so it only limits contestants who
drive the gameloop. A contestant posting straight to ``/actions/submit`` had no
pacing limit and no per-cycle ceiling, and ``submit-batch`` and ``interpret``
accepted unbounded lists. Every bundled example uses that path, so in practice the
budget bound almost nobody.

This enforces the same limits where actions enter the server.

Why per COMPANY rather than per agent: scoring is per company, and several agents
legitimately share one -- the shipped 3-agent scenario puts road, air, and water all
on company 0. A per-agent budget would hand a 3-agent entry three times the actions
of a 1-agent entry on the same scenario.

The window is a sliding count rather than a token bucket: the question a benchmark
needs answered is "how many actions did this company take in the last
poll_interval", which is what a per-cycle ceiling means once cycles are not the unit
of submission.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
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
    """Sliding-window action budget, keyed by company.

    Attributes:
        max_actions: Actions permitted per window. 0 disables the limit.
        window_seconds: Length of the sliding window, normally poll_interval.
        enforced: Whether to refuse. False records usage without blocking, so an
            unscored session still reports what a contestant did.
    """

    max_actions: int = 0
    window_seconds: float = 0.0
    enforced: bool = False
    _timestamps: dict[int, deque[float]] = field(
        default_factory=lambda: defaultdict(deque), repr=False,
    )
    _refused: dict[int, int] = field(default_factory=lambda: defaultdict(int), repr=False)

    def _prune(self, company_id: int, now: float) -> deque[float]:
        """Drop timestamps that have fallen out of the window."""
        stamps = self._timestamps[company_id]
        cutoff = now - self.window_seconds
        while stamps and stamps[0] < cutoff:
            stamps.popleft()
        return stamps

    def check(self, company_id: int, count: int = 1) -> BudgetDecision:
        """Test whether ``count`` more actions fit, without consuming budget."""
        if not self.enforced or self.max_actions <= 0 or self.window_seconds <= 0:
            return BudgetDecision(allowed=True)

        stamps = self._prune(company_id, time.monotonic())
        used = len(stamps)
        if used + count <= self.max_actions:
            return BudgetDecision(allowed=True, used=used, limit=self.max_actions)

        self._refused[company_id] += count
        return BudgetDecision(
            allowed=False,
            reason=(
                f"company {company_id} has used {used} of {self.max_actions} actions "
                f"in the last {self.window_seconds:g}s; {count} more would exceed the "
                f"scenario's budget"
            ),
            used=used,
            limit=self.max_actions,
        )

    def consume(self, company_id: int, count: int = 1) -> None:
        """Record ``count`` actions against a company's window.

        Recorded even when unenforced, so ``usage`` reflects what happened.
        """
        now = time.monotonic()
        stamps = self._prune(company_id, now)
        stamps.extend([now] * max(0, count))

    def usage(self) -> dict[str, object]:
        """Flatten for the result record."""
        return {
            "enforced": self.enforced,
            "max_actions_per_window": self.max_actions,
            "window_seconds": self.window_seconds,
            "refused_actions": {str(k): v for k, v in sorted(self._refused.items())},
            "total_refused": sum(self._refused.values()),
        }


def from_fairness(fairness: object) -> ActionBudget:
    """Build a budget from a FairnessConfig.

    The window is poll_interval, so the REST path is held to the same rate a
    gameloop agent is: max_actions_per_cycle actions per poll_interval.
    """
    return ActionBudget(
        max_actions=int(getattr(fairness, "max_actions_per_cycle", 0) or 0),
        window_seconds=float(getattr(fairness, "poll_interval", 0.0) or 0.0),
        enforced=bool(getattr(fairness, "enforced", False)),
    )
