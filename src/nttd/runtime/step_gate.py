"""Serialises the stepped loop for the one company playing a session.

This was a barrier, and the name was accurate while a session could hold several
contestant companies stepping one shared world. It had to gather a step from each of
them before advancing, because there is one clock and N companies cannot each hold their
own: measured on a two-company session, both companies took one step and the world moved
**60** days when the calls were staggered and **30** when they arrived together.

A session now holds one contestant, so there is nothing to gather. A multi-agent entry is
several agents driving that one company, and its orchestrator decides what the company
does before submitting: one batch, one step. The barrier's registration set, windows,
eviction and liveness timeout all existed to answer "who else are we waiting for", and
the answer is now always "nobody".

What is left is the part that was never about multiple companies:

**Reset before step.** ``/step`` on a session that never entered stepped mode is a
mistake worth naming, not a world advance. Registration is what distinguishes them.

**One step in flight.** Two concurrent ``/step`` calls would each advance the world, so
"one step" would mean one or two advances depending on timing. Refused rather than
queued, because a caller that issued two has a bug and silently serialising hides it.

Deliberately not a lock. A lock would make the second caller wait and then succeed, which
is the behaviour that hides the bug.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from nttd.runtime.step_errors import NotRegisteredForStepping, StepAlreadyInFlight
from nttd.schemas.step_result import StepResult

logger = logging.getLogger(__name__)

AdvanceFn = Callable[[list[dict[str, Any]]], Awaitable[StepResult]]


class StepGate:
    """Admits one step at a time, for the one company registered to step."""

    def __init__(self) -> None:
        self._company: int | None = None
        self._in_flight = False
        self._steps = 0

    @property
    def registered(self) -> frozenset[int]:
        """The company expected to step, or empty before reset.

        A set rather than an optional int because callers ask "is this company allowed
        to step", and that question has the same shape whether the answer comes from one
        company or several.
        """
        return frozenset() if self._company is None else frozenset({self._company})

    @property
    def steps(self) -> int:
        """How many advances this gate has driven."""
        return self._steps

    def register(self, company_id: int) -> None:
        """Declare that this company is stepping.

        Idempotent, because ``/step/reset`` is: calling it again re-pauses and
        re-observes without restarting the world, and it should not matter to the gate
        how many times that happened.
        """
        if self._company is not None and self._company != company_id:
            logger.warning(
                "Company %d is already stepping this session; company %d cannot join. "
                "A session holds one contestant, so several agents driving one company "
                "submit through one runner rather than registering separately",
                self._company, company_id,
            )
            return
        self._company = company_id

    def unregister(self, company_id: int) -> None:
        """Stop expecting this company to step."""
        if self._company == company_id:
            self._company = None

    async def arrive(
        self,
        company_id: int,
        batch: list[dict[str, Any]],
        advance: AdvanceFn,
    ) -> StepResult:
        """Flush this batch, advance the world once, and return the new observation.

        Raises:
            NotRegisteredForStepping: this company never called ``/step/reset``.
            StepAlreadyInFlight: this company already has a step in flight.
        """
        if company_id not in self.registered:
            raise NotRegisteredForStepping(company_id)
        if self._in_flight:
            raise StepAlreadyInFlight(company_id)

        self._in_flight = True
        try:
            result = await advance(list(batch))
        finally:
            # Cleared even when the advance raises. Leaving it set would make one failed
            # step refuse every step after it, turning a recoverable error into a dead
            # session.
            self._in_flight = False

        self._steps += 1
        return result
