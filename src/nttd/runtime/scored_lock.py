"""The scored-session lock: what actually protects a benchmark run.

nttd is self-hosted, so a contestant controls the process and holds every
credential. Authentication therefore cannot protect a scored run -- the trust
tiers are namespacing, and the participant token is addressing. Neither is a wall.

What does work is session STATE. A session marked scored refuses game-mutating
operator operations for the whole of its life, for every caller, regardless of what
they present. There is no credential to hold, so there is nothing to hold wrongly.

This does not stop a determined self-hoster: they can edit the config, patch the
GameScript, or rewrite the parquet files. It stops the failure that actually
happens -- an agent or operator reaching for a deity power and silently
invalidating an otherwise legitimate run. Every refusal is recorded like any other
action, so the attempt is auditable rather than merely prevented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockedAttempt:
    """One refused operation, recorded with the same detail as an action."""

    operation: str
    detail: str
    game_date: int
    attempted_at: datetime


@dataclass
class ScoredLock:
    """Tracks whether a session is scored, and what it refused.

    Attributes:
        scored: When True, game-mutating operator operations are refused.
        blocked: Every refusal, in order, for the result record.
    """

    scored: bool = False
    blocked: list[BlockedAttempt] = field(default_factory=list)

    def check(self, operation: str, game_date: int = 0, detail: str = "") -> bool:
        """Return True if ``operation`` is permitted.

        A refusal is recorded before returning False, so the caller only has to
        decide how to report it.
        """
        if not self.scored:
            return True

        attempt = BlockedAttempt(
            operation=operation,
            detail=detail,
            game_date=game_date,
            attempted_at=datetime.now(timezone.utc),
        )
        self.blocked.append(attempt)
        logger.warning(
            "Scored session refused operator operation %s (game_date=%d)%s",
            operation, game_date, f": {detail}" if detail else "",
        )
        return False

    @property
    def clean_run(self) -> bool:
        """True if nothing was refused.

        Refusals do not void a run -- nothing happened, so the result stands. The
        flag records that something was attempted, which is what makes an accident
        visible instead of silent.
        """
        return not self.blocked

    def summary(self) -> dict[str, object]:
        """Flatten for the result record."""
        return {
            "scored": self.scored,
            "clean_run": self.clean_run,
            "blocked_attempts": len(self.blocked),
            "blocked_operations": sorted({a.operation for a in self.blocked}),
        }
