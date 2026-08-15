"""The gate that admits one step at a time for the one company playing a session.

This replaces a barrier and the tests that went with it. The barrier gathered a step
from each of several contestant companies before advancing the shared clock, because
the bug it existed to prevent was measured on a live two-company session: each company
took one step and the world advanced 60 days when the calls were staggered, 30 when they
arrived together. A benchmark cannot have "ten steps" mean a different amount of world
depending on request timing.

A session now holds one contestant, so that bug is unreachable rather than guarded
against, and the tests for windows, eviction and merged batches went with the code. What
survives is everything that was never about several companies.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nttd.runtime.step_errors import NotRegisteredForStepping, StepAlreadyInFlight
from nttd.runtime.step_gate import StepGate
from nttd.schemas.game import GameState
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.step_result import StepResult

INTERVAL_DAYS = 30


class FakeWorld:
    """A world with one clock, and a count of how often it moved."""

    def __init__(self, start_date: int = 1000) -> None:
        self.date = start_date
        self.advances = 0
        self.flushed: list[list[dict[str, Any]]] = []
        self.advance_delay = 0.0
        self.fail_next = False

    async def advance(self, batch: list[dict[str, Any]]) -> StepResult:
        self.flushed.append(list(batch))
        if self.advance_delay:
            await asyncio.sleep(self.advance_delay)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("the world refused to move")
        self.date += INTERVAL_DAYS
        self.advances += 1
        return StepResult(
            snapshot=StateSnapshot(game=GameState(game_date=self.date)),
            step=self.advances,
            days_advanced=INTERVAL_DAYS,
        )


def action(company_id: int) -> dict[str, Any]:
    return {"action": "set_loan", "params": {"company_id": company_id, "amount": 1}}


class TestSteppingTheWorld:
    @pytest.mark.asyncio
    async def test_a_step_advances_the_world_once(self) -> None:
        world = FakeWorld()
        gate = StepGate()
        gate.register(0)

        result = await gate.arrive(0, [action(0)], world.advance)

        assert world.advances == 1
        assert result.days_advanced == INTERVAL_DAYS

    @pytest.mark.asyncio
    async def test_k_steps_advance_k_intervals(self) -> None:
        """The property the barrier existed to protect, and the one thing here that
        must stay true however the gate is written."""
        world = FakeWorld()
        gate = StepGate()
        gate.register(0)

        for _ in range(5):
            await gate.arrive(0, [], world.advance)

        assert world.advances == 5
        assert world.date == 1000 + 5 * INTERVAL_DAYS
        assert gate.steps == 5

    @pytest.mark.asyncio
    async def test_the_batch_reaches_the_world_intact(self) -> None:
        world = FakeWorld()
        gate = StepGate()
        gate.register(0)

        await gate.arrive(0, [action(0), action(0)], world.advance)

        assert world.flushed == [[action(0), action(0)]]

    @pytest.mark.asyncio
    async def test_a_step_with_no_actions_still_advances(self) -> None:
        """Waiting is a move. A policy that does nothing this step is making a choice,
        not failing to make one."""
        world = FakeWorld()
        gate = StepGate()
        gate.register(0)

        await gate.arrive(0, [], world.advance)

        assert world.advances == 1


class TestRefusals:
    @pytest.mark.asyncio
    async def test_stepping_without_registering_is_refused(self) -> None:
        """Served silently it would advance the world, and the caller would have a
        running clock it did not know it had started."""
        world = FakeWorld()
        gate = StepGate()

        with pytest.raises(NotRegisteredForStepping):
            await gate.arrive(0, [], world.advance)

        assert world.advances == 0

    @pytest.mark.asyncio
    async def test_a_second_concurrent_step_is_refused(self) -> None:
        """Refused rather than queued. Serialising them would let a caller with a bug
        get a result that looks correct, having advanced the world twice for one step."""
        world = FakeWorld()
        world.advance_delay = 0.05
        gate = StepGate()
        gate.register(0)

        in_flight = asyncio.create_task(gate.arrive(0, [action(0)], world.advance))
        await asyncio.sleep(0.01)

        with pytest.raises(StepAlreadyInFlight):
            await gate.arrive(0, [action(0)], world.advance)

        await in_flight
        assert world.advances == 1

    @pytest.mark.asyncio
    async def test_a_second_company_cannot_join(self) -> None:
        """The API refuses a second contestant at session start, so this should be
        unreachable. Held here anyway: a gate that quietly accepted one would advance
        the world on somebody else's schedule."""
        world = FakeWorld()
        gate = StepGate()
        gate.register(0)
        gate.register(1)

        assert gate.registered == frozenset({0})
        with pytest.raises(NotRegisteredForStepping):
            await gate.arrive(1, [], world.advance)


class TestAFailedStep:
    @pytest.mark.asyncio
    async def test_the_failure_reaches_the_caller(self) -> None:
        world = FakeWorld()
        world.fail_next = True
        gate = StepGate()
        gate.register(0)

        with pytest.raises(RuntimeError, match="refused to move"):
            await gate.arrive(0, [], world.advance)

    @pytest.mark.asyncio
    async def test_it_does_not_wedge_the_gate(self) -> None:
        """The in-flight flag is cleared in a finally. Left set, one failed step would
        refuse every step after it and a recoverable error would end the run."""
        world = FakeWorld()
        world.fail_next = True
        gate = StepGate()
        gate.register(0)

        with pytest.raises(RuntimeError):
            await gate.arrive(0, [], world.advance)

        result = await gate.arrive(0, [], world.advance)
        assert result.days_advanced == INTERVAL_DAYS
        assert world.advances == 1

    @pytest.mark.asyncio
    async def test_a_failed_step_is_not_counted(self) -> None:
        world = FakeWorld()
        world.fail_next = True
        gate = StepGate()
        gate.register(0)

        with pytest.raises(RuntimeError):
            await gate.arrive(0, [], world.advance)

        assert gate.steps == 0


class TestRegistration:
    def test_nothing_is_registered_before_reset(self) -> None:
        assert StepGate().registered == frozenset()

    def test_registering_twice_is_idempotent(self) -> None:
        """``/step/reset`` is idempotent, so this has to be: calling it again re-pauses
        and re-observes without restarting the world."""
        gate = StepGate()
        gate.register(0)
        gate.register(0)
        assert gate.registered == frozenset({0})

    def test_unregistering_stops_the_stepper(self) -> None:
        gate = StepGate()
        gate.register(0)
        gate.unregister(0)
        assert gate.registered == frozenset()

    def test_unregistering_somebody_else_does_nothing(self) -> None:
        gate = StepGate()
        gate.register(0)
        gate.unregister(1)
        assert gate.registered == frozenset({0})
