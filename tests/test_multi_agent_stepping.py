"""Several companies stepping one shared world.

The bug this exists to prevent, measured on a live two-company session before the
barrier: each company took one step and the world advanced 60 days when the calls were
staggered, 30 when they arrived together. A benchmark cannot have "ten steps" mean a
different amount of world depending on request timing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nttd.runtime.step_barrier import StepBarrier
from nttd.runtime.step_errors import AlreadyWaitingAtBarrier, NotRegisteredForStepping
from nttd.schemas.game import GameState
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.step_result import StepResult

INTERVAL_DAYS = 30


class FakeWorld:
    """A world with one clock, which is the whole reason the barrier exists."""

    def __init__(self, start_date: int = 1000) -> None:
        self.date = start_date
        self.advances = 0
        self.flushed: list[list[dict[str, Any]]] = []
        self.advance_delay = 0.0

    async def advance(self, batches: list[dict[str, Any]]) -> StepResult:
        self.flushed.append(list(batches))
        if self.advance_delay:
            await asyncio.sleep(self.advance_delay)
        self.date += INTERVAL_DAYS
        self.advances += 1
        return StepResult(
            snapshot=StateSnapshot(game=GameState(game_date=self.date)),
            step=self.advances,
            days_advanced=INTERVAL_DAYS,
        )


def action(company_id: int) -> dict[str, Any]:
    return {"action": "set_loan", "params": {"company_id": company_id, "amount": 1}}


class TestOneStepper:
    """A single-company session must behave exactly as it did before the barrier."""

    @pytest.mark.asyncio
    async def test_a_lone_stepper_advances_immediately(self) -> None:
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)

        result = await barrier.arrive(0, [action(0)], world.advance)

        assert world.advances == 1
        assert result.days_advanced == INTERVAL_DAYS
        assert result.steppers == [0]

    @pytest.mark.asyncio
    async def test_k_steps_advance_k_intervals(self) -> None:
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)

        for _ in range(4):
            await barrier.arrive(0, [], world.advance)

        assert world.date == 1000 + 4 * INTERVAL_DAYS


class TestTwoSteppers:
    @pytest.mark.asyncio
    async def test_concurrent_steps_advance_the_world_once(self) -> None:
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)
        barrier.register(1)

        results = await asyncio.gather(
            barrier.arrive(0, [action(0)], world.advance),
            barrier.arrive(1, [action(1)], world.advance),
        )

        assert world.advances == 1
        assert world.date == 1000 + INTERVAL_DAYS
        for result in results:
            assert result.days_advanced == INTERVAL_DAYS
            assert result.steppers == [0, 1]

    @pytest.mark.asyncio
    async def test_staggered_steps_also_advance_the_world_once(self) -> None:
        """The measured bug: staggered arrival used to advance the world twice."""
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)
        barrier.register(1)

        first = asyncio.create_task(barrier.arrive(0, [action(0)], world.advance))
        await asyncio.sleep(0.05)
        assert world.advances == 0, "the world moved before every stepper arrived"

        second = asyncio.create_task(barrier.arrive(1, [action(1)], world.advance))
        await asyncio.gather(first, second)

        assert world.advances == 1
        assert world.date == 1000 + INTERVAL_DAYS

    @pytest.mark.asyncio
    async def test_both_companies_actions_reach_the_same_flush(self) -> None:
        """Company 1 arrives FIRST, so arrival order and company order disagree.

        With both arriving in company order this assertion held either way, and a
        mutation that flushed in arrival order passed all twenty tests.
        """
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)
        barrier.register(1)

        late = asyncio.create_task(barrier.arrive(1, [action(1)], world.advance))
        await asyncio.sleep(0.05)
        first = asyncio.create_task(
            barrier.arrive(0, [action(0), action(0)], world.advance),
        )
        await asyncio.gather(late, first)

        assert len(world.flushed) == 1
        companies = [a["params"]["company_id"] for a in world.flushed[0]]
        assert companies == [0, 0, 1], (
            "flushed in arrival order; which company called first must not decide "
            "whose road gets built on a contested tile"
        )

    @pytest.mark.asyncio
    async def test_the_number_of_steps_matches_a_single_agent_run(self) -> None:
        """Comparability: N companies times K steps is K intervals, same as one."""
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)
        barrier.register(1)

        for _ in range(3):
            await asyncio.gather(
                barrier.arrive(0, [], world.advance),
                barrier.arrive(1, [], world.advance),
            )

        assert world.advances == 3
        assert world.date == 1000 + 3 * INTERVAL_DAYS

    @pytest.mark.asyncio
    async def test_both_receive_the_same_observation(self) -> None:
        """One world, one post-step state: two companies cannot disagree about it."""
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)
        barrier.register(1)

        a, b = await asyncio.gather(
            barrier.arrive(0, [], world.advance),
            barrier.arrive(1, [], world.advance),
        )

        assert a.snapshot.game.game_date == b.snapshot.game.game_date
        assert a.step == b.step


class TestRefusals:
    @pytest.mark.asyncio
    async def test_stepping_without_registering_is_refused(self) -> None:
        world = FakeWorld()
        barrier = StepBarrier()
        with pytest.raises(NotRegisteredForStepping):
            await barrier.arrive(0, [], world.advance)

    @pytest.mark.asyncio
    async def test_a_second_concurrent_step_from_one_company_is_refused(self) -> None:
        """Two batches from one company in one window is the ceiling bypass again."""
        world = FakeWorld()
        barrier = StepBarrier()
        barrier.register(0)
        barrier.register(1)

        waiting = asyncio.create_task(barrier.arrive(0, [action(0)], world.advance))
        await asyncio.sleep(0.05)

        with pytest.raises(AlreadyWaitingAtBarrier):
            await barrier.arrive(0, [action(0)], world.advance)

        await barrier.arrive(1, [], world.advance)
        await waiting


class TestEviction:
    @pytest.mark.asyncio
    async def test_a_silent_stepper_is_evicted_and_the_run_continues(self) -> None:
        """A crashed runner must not hang the session for everyone else."""
        world = FakeWorld()
        barrier = StepBarrier(liveness_timeout=0.1)
        barrier.register(0)
        barrier.register(1)

        result = await barrier.arrive(0, [action(0)], world.advance)

        assert world.advances == 1
        assert barrier.evicted == frozenset({1})
        assert barrier.registered == frozenset({0})
        assert result.steppers == [0]

    @pytest.mark.asyncio
    async def test_eviction_is_reported_so_it_can_be_recorded(self) -> None:
        world = FakeWorld()
        barrier = StepBarrier(liveness_timeout=0.1)
        evicted: list[int] = []
        barrier.set_evict_callback(evicted.append)
        barrier.register(0)
        barrier.register(1)

        await barrier.arrive(0, [], world.advance)

        assert evicted == [1]

    @pytest.mark.asyncio
    async def test_an_evicted_company_does_not_rejoin(self) -> None:
        """Otherwise a flapping runner would stall a window every time it dropped."""
        world = FakeWorld()
        barrier = StepBarrier(liveness_timeout=0.1)
        barrier.register(0)
        barrier.register(1)
        await barrier.arrive(0, [], world.advance)

        barrier.register(1)
        assert barrier.registered == frozenset({0})

    @pytest.mark.asyncio
    async def test_a_slow_but_present_stepper_is_never_truncated(self) -> None:
        """No decision deadline. Removing wall-clock pressure is the point of stepping.

        The timeout is a liveness proxy, so a company that arrives late but does arrive
        must still have its actions flushed rather than dropped.
        """
        world = FakeWorld()
        barrier = StepBarrier(liveness_timeout=0.4)
        barrier.register(0)
        barrier.register(1)

        first = asyncio.create_task(barrier.arrive(0, [action(0)], world.advance))
        await asyncio.sleep(0.2)
        second = asyncio.create_task(barrier.arrive(1, [action(1)], world.advance))
        await asyncio.gather(first, second)

        assert barrier.evicted == frozenset()
        companies = [a["params"]["company_id"] for a in world.flushed[0]]
        assert companies == [0, 1]


class TestFailurePropagation:
    @pytest.mark.asyncio
    async def test_a_failed_advance_reaches_every_waiter(self) -> None:
        """Otherwise the waiters sit until the liveness timeout on a dead window."""
        barrier = StepBarrier(liveness_timeout=5.0)
        barrier.register(0)
        barrier.register(1)

        async def failing(_batches: list[dict[str, Any]]) -> StepResult:
            raise RuntimeError("gamescript wedged")

        results = await asyncio.gather(
            barrier.arrive(0, [], failing),
            barrier.arrive(1, [], failing),
            return_exceptions=True,
        )

        assert len(results) == 2
        for outcome in results:
            assert isinstance(outcome, RuntimeError)
            assert "gamescript wedged" in str(outcome)

    @pytest.mark.asyncio
    async def test_the_barrier_recovers_after_a_failed_window(self) -> None:
        world = FakeWorld()
        barrier = StepBarrier(liveness_timeout=5.0)
        barrier.register(0)

        async def failing(_batches: list[dict[str, Any]]) -> StepResult:
            raise RuntimeError("transient")

        with pytest.raises(RuntimeError):
            await barrier.arrive(0, [], failing)

        result = await barrier.arrive(0, [], world.advance)
        assert result.days_advanced == INTERVAL_DAYS


class TestArrivalDuringAnAdvance:
    @pytest.mark.asyncio
    async def test_a_late_batch_lands_in_the_next_window(self) -> None:
        """A batch must not be flushed into a world that is already moving.

        The step barrier's ordering guarantee is that a batch executes at a known point.
        Merging one into an advance already under way breaks exactly that.
        """
        world = FakeWorld()
        world.advance_delay = 0.3
        barrier = StepBarrier()
        barrier.register(0)

        driving = asyncio.create_task(barrier.arrive(0, [action(0)], world.advance))
        await asyncio.sleep(0.1)
        late = asyncio.create_task(barrier.arrive(0, [action(0)], world.advance))

        await asyncio.gather(driving, late)

        assert world.advances == 2
        assert len(world.flushed) == 2
        assert len(world.flushed[0]) == 1
        assert len(world.flushed[1]) == 1


class TestParallelEnv:
    """One process holding every company, the PettingZoo shape.

    The independent shape needs nothing here: N processes each hold one NttdEnv and the
    server's barrier synchronises them. This class is for self-play and population
    training, where one loop owns all N.
    """

    @staticmethod
    def _env(step_hook: Any) -> Any:
        from nttd.rl.multi_env import NttdParallelEnv

        env = NttdParallelEnv(session_id="ses_x", tokens={0: "pt_a", 1: "pt_b"})
        for member in env._envs.values():
            member._post = step_hook
        return env

    def test_at_least_one_company_is_required(self) -> None:
        from nttd.rl.multi_env import NttdParallelEnv

        with pytest.raises(ValueError, match="at least one company token"):
            NttdParallelEnv(session_id="ses_x", tokens={})

    def test_every_company_steps_even_if_the_caller_omits_one(self) -> None:
        """The barrier waits for every registered stepper.

        Skipping an agent whose policy returned nothing would stall the window until
        the liveness timeout evicted it, so a missing entry becomes an empty batch.
        """
        submitted: list[Any] = []

        def hook(suffix: str, payload: Any, _timeout: float) -> dict[str, Any]:
            if suffix == "step":
                submitted.append((payload or {}).get("actions"))
            return {"snapshot": {"game": {"game_date": 100}, "companies": []}, "step": 1}

        env = self._env(hook)
        env.reset()
        env.step({"company_0": [{"action": "set_loan", "params": {}}]})

        assert len(submitted) == 2, "a company was skipped and would have stalled the window"
        assert [] in submitted, "the omitted company did not submit an empty batch"
        env.close()

    def test_the_step_calls_are_in_flight_together(self) -> None:
        """Serialised calls would deadlock: each blocks until the window closes.

        The fake refuses to answer until every company has arrived, which is exactly
        what the real barrier does.
        """
        import threading

        arrived = threading.Barrier(2, timeout=5.0)

        def hook(suffix: str, _payload: Any, _timeout: float) -> dict[str, Any]:
            if suffix == "step":
                arrived.wait()
            return {"snapshot": {"game": {"game_date": 100}, "companies": []}, "step": 1}

        env = self._env(hook)
        env.reset()
        # Raises threading.BrokenBarrierError on timeout if the calls were serialised.
        env.step({"company_0": [], "company_1": []})
        env.close()

    def test_a_terminated_run_empties_the_agent_list(self) -> None:
        """One world, one set of end conditions: the run ends for everyone at once."""
        def hook(_suffix: str, _payload: Any, _timeout: float) -> dict[str, Any]:
            return {
                "snapshot": {"game": {"game_date": 100}, "companies": []},
                "step": 1, "terminated": True, "end_reason": "bankruptcy",
            }

        env = self._env(hook)
        env.reset()
        _, _, terminations, _, _ = env.step({})

        assert all(terminations.values())
        assert env.agents == []
        env.close()
