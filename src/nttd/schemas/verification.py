"""What a verification run concludes, and how sure it is.

The verdict is deliberately three-valued rather than a boolean. nttd is self-hosted, so
"we watched it happen" is never available; what is available is "the score is
recomputable from the save" (cheap, and the useful default) and additionally "the world
is the world that was declared" (expensive, and what separates a real benchmark run from
a hand-picked one).

**A verdict is not stored in a bundle.** It belongs to whoever computed it, on hardware
they control. A bundle carrying its own verdict would be asserting something anyone could
write, which is the same defect as a scenario declaring ``scored = true``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Verdict(StrEnum):
    """How much of a submission a verifier was able to confirm."""

    VERIFIED = "verified"
    """Everything checked passed, including that the world matches its declared seed."""

    REPLAYED = "replayed"
    """The score was recomputed from the savegame, but the world was not reconciled.

    Either the regeneration check was not requested, or it could not be completed. This
    is the default bar: cheap, and it already rules out a score that the save does not
    support.
    """

    UNVERIFIED = "unverified"
    """The artifacts do not support checking. The score is self-reported."""


class CheckOutcome(BaseModel):
    """One check's result, in a form a leaderboard's ingest can act on.

    Attributes:
        name: Stable identifier, so a board can filter on it without parsing prose.
        passed: None when the check was not attempted, which is different from failing.
        detail: One line a human can read. Written to be useful in a table cell.
    """

    name: str
    passed: bool | None = None
    detail: str = ""


class VerificationReport(BaseModel):
    """The full outcome of verifying one bundle.

    Attributes:
        verdict: The three-valued conclusion.
        advisory: True when this was produced by ``nttd verify`` on a contestant's own
            machine. Such a verdict predicts what a board will say and carries no weight
            of its own, because whoever ran it could have changed the code that produced
            it.
        session_id: From the bundle's manifest.
        task_id: From the bundle's manifest, so rows can be grouped without opening the
            Parquet.
        checks: One outcome per check, in the order they ran.
    """

    verdict: Verdict
    advisory: bool = True
    session_id: str = ""
    task_id: str = ""
    checks: list[CheckOutcome] = Field(default_factory=list)

    @property
    def failures(self) -> list[CheckOutcome]:
        """Checks that ran and did not pass."""
        return [check for check in self.checks if check.passed is False]

    @property
    def skipped(self) -> list[CheckOutcome]:
        """Checks that were not attempted."""
        return [check for check in self.checks if check.passed is None]
