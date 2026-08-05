"""Synchronises several companies stepping one shared world.

There is one OpenTTD world with one clock, so N companies cannot each hold their own.
Left unsynchronised, each ``POST /step`` advances the world on its own, and the game
time a session covers depends on how the calls happened to interleave. Measured on a
two-company session: both companies took one step and the world advanced **60** days
when the calls were staggered and **30** when they arrived together. A benchmark cannot
have "ten steps" mean a different amount of world depending on request timing.

So the clock is synchronised and participation is not. A window opens when the first
company arrives and closes when every registered stepper has arrived; the last arriver
drives the single world advance and everyone receives the same post-advance
observation. N companies times K steps is K windows, which is K times the interval, the
same as one company stepping K times.

Nobody is blocked on anybody's *thinking*. There is no decision deadline, because
removing wall-clock pressure from deliberation is the whole point of stepping. The only
timeout is a liveness one, set far above any real deliberation: a registered stepper
that goes silent past it is evicted for the rest of the run and the window closes
without it, so a crashed runner cannot hang a session.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from nttd.runtime.step_errors import AlreadyWaitingAtBarrier, NotRegisteredForStepping
from nttd.schemas.step_result import StepResult

logger = logging.getLogger(__name__)

# Ten minutes. A liveness proxy, not a decision deadline: over HTTP a runner that is
# thinking hard is indistinguishable from one that has died, and this is set far enough
# above any real deliberation that only the second case should ever reach it.
DEFAULT_LIVENESS_TIMEOUT_SECONDS = 600.0

AdvanceFn = Callable[[list[dict[str, Any]]], Awaitable[StepResult]]


class StepBarrier:
    """Gathers one step from each registered company into a single world advance."""

    def __init__(self, liveness_timeout: float = DEFAULT_LIVENESS_TIMEOUT_SECONDS) -> None:
        self._liveness_timeout = liveness_timeout
        self._registered: set[int] = set()
        self._evicted: set[int] = set()
        self._arrived: dict[int, list[dict[str, Any]]] = {}
        self._condition = asyncio.Condition()
        self._window = 0
        self._closing = False
        self._results: dict[int, StepResult] = {}
        self._errors: dict[int, BaseException] = {}
        self._on_evict: Callable[[int], None] | None = None

    @property
    def registered(self) -> frozenset[int]:
        """Companies expected to arrive at each window."""
        return frozenset(self._registered)

    @property
    def evicted(self) -> frozenset[int]:
        """Companies dropped for going silent. They do not rejoin."""
        return frozenset(self._evicted)

    @property
    def window(self) -> int:
        """How many windows have closed."""
        return self._window

    def set_evict_callback(self, callback: Callable[[int], None]) -> None:
        """Register a callback invoked when a company is evicted, for recording it."""
        self._on_evict = callback

    def register(self, company_id: int) -> None:
        """Declare that a company will be stepping.

        Registration is explicit rather than inferred from the session's company count,
        so a session whose second runner never attaches does not stall every window
        waiting for it.
        """
        if company_id in self._evicted:
            logger.warning(
                "Company %d was evicted for going silent and does not rejoin", company_id,
            )
            return
        self._registered.add(company_id)

    def unregister(self, company_id: int) -> None:
        """Stop expecting a company at the barrier."""
        self._registered.discard(company_id)
        self._arrived.pop(company_id, None)

    async def arrive(
        self,
        company_id: int,
        batch: list[dict[str, Any]],
        advance: AdvanceFn,
    ) -> StepResult:
        """Submit one company's step and return once the world has advanced.

        Raises:
            NotRegisteredForStepping: the company never called ``/step/reset``.
            AlreadyWaitingAtBarrier: this company already has a step in flight.
        """
        async with self._condition:
            # A window mid-advance is already committed. Wait for it rather than
            # joining it, so this batch lands in the next window instead of being
            # flushed into a world that is already moving.
            while self._closing:
                await self._condition.wait()

            if company_id not in self._registered:
                raise NotRegisteredForStepping(company_id)
            if company_id in self._arrived:
                raise AlreadyWaitingAtBarrier(company_id)

            self._arrived[company_id] = list(batch)
            my_window = self._window
            drive = self._is_complete()
            if drive:
                self._closing = True
                batches = self._collect()
                participants = sorted(self._arrived)

        if drive:
            return await self._advance_and_publish(my_window, batches, participants, advance)
        return await self._wait_for_window(company_id, my_window, advance)

    def _is_complete(self) -> bool:
        """Whether every registered stepper has arrived at the open window."""
        return self._registered.issubset(self._arrived.keys())

    def _collect(self) -> list[dict[str, Any]]:
        """Flatten the arrived batches in company order, for a reproducible flush.

        Company order rather than arrival order: which company happened to call first
        should not decide whose road gets built on a contested tile.
        """
        actions: list[dict[str, Any]] = []
        for company_id in sorted(self._arrived):
            actions.extend(self._arrived[company_id])
        return actions

    async def _advance_and_publish(
        self,
        my_window: int,
        batches: list[dict[str, Any]],
        participants: list[int],
        advance: AdvanceFn,
    ) -> StepResult:
        """Drive the one world advance for this window, then wake the other steppers.

        The condition is not held during the advance, which takes real wall-clock time.
        ``_closing`` is what keeps a late arrival out in the meantime.
        """
        result: StepResult | None = None
        error: BaseException | None = None
        try:
            result = await advance(batches)
            # Stamped here because only the barrier knows who was in the window. The
            # orchestrator advances the world and has no idea how many companies asked.
            result.steppers = participants
        except BaseException as exc:  # noqa: BLE001 -- re-raised below, after waking waiters
            error = exc

        async with self._condition:
            if error is not None:
                # Every waiter has to see the failure, otherwise they sit here until
                # the liveness timeout for a window that will never close.
                self._errors[my_window] = error
            else:
                self._results[my_window] = result
            self._window = my_window + 1
            self._arrived.clear()
            self._closing = False
            self._prune(my_window)
            self._condition.notify_all()

        if error is not None:
            raise error
        return result

    async def _wait_for_window(
        self, company_id: int, my_window: int, advance: AdvanceFn,
    ) -> StepResult:
        """Wait for another company to close this window, evicting anyone silent."""
        while True:
            async with self._condition:
                if self._window > my_window:
                    return self._published(my_window)

                try:
                    await asyncio.wait_for(
                        self._condition.wait(), timeout=self._liveness_timeout,
                    )
                    continue
                except (TimeoutError, asyncio.TimeoutError):
                    pass

                if self._window > my_window:
                    return self._published(my_window)

                missing = self._registered - self._arrived.keys() - {company_id}
                if not missing:
                    # Nobody left to blame: another arriver is presumably driving an
                    # advance that is simply slow. Keep waiting.
                    continue

                for silent in sorted(missing):
                    self._evict(silent)

                if not self._is_complete():
                    continue

                self._closing = True
                batches = self._collect()
                participants = sorted(self._arrived)

            # Eviction made this company the last arriver, so it drives the advance.
            return await self._advance_and_publish(
                my_window, batches, participants, advance,
            )

    def _evict(self, company_id: int) -> None:
        """Drop a silent company so the remaining steppers are not held up."""
        logger.warning(
            "Company %d did not step within %.0fs and is evicted from the barrier; "
            "the run continues without it",
            company_id, self._liveness_timeout,
        )
        self._registered.discard(company_id)
        self._evicted.add(company_id)
        if self._on_evict is not None:
            self._on_evict(company_id)

    def _published(self, window: int) -> StepResult:
        """Return what the window produced, raising if the advance failed."""
        error = self._errors.get(window)
        if error is not None:
            raise error
        result = self._results.get(window)
        if result is None:
            raise RuntimeError(f"Step window {window} closed without a result")
        return result

    def _prune(self, window: int) -> None:
        """Keep only the most recent windows, so a long run does not accumulate them."""
        for old in [w for w in self._results if w < window - 1]:
            del self._results[old]
        for old in [w for w in self._errors if w < window - 1]:
            del self._errors[old]
