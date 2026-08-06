"""Only a one-company run is scoreable.

A scored result is one company's performance on one world. A session with several
participant tokens is a different problem: co-contestants sharing a map, competing for
the same towns and industries. Two such runs are not comparable with each other, and
neither is comparable with a solo run on the same world, yet nothing on a result row
records which it was.

Multi-company sessions remain useful and available. Self-play and population training
want exactly that shape and `NttdParallelEnv` drives it. They are simply not scored.

The rule could not go in the profile check with the others: the count arrives as an
argument to `start_session`, not from the scenario, so `resolve_scored` cannot see it.
`_agent_companies` is also excluded from `task_id` by design, so nothing else was
catching it either.
"""

from __future__ import annotations

import pytest

from nttd.config import single_company


class TestTheRule:
    @pytest.mark.parametrize("count", [0, 1])
    def test_one_or_none_is_scoreable(self, count: int) -> None:
        """Zero is a session nobody plays through the participant routes, which is what
        a human entry recorded over CMD_LOGGING looks like."""
        assert single_company.blocks_scoring(count) is None

    @pytest.mark.parametrize("count", [2, 3, 15])
    def test_more_than_one_is_not(self, count: int) -> None:
        assert single_company.blocks_scoring(count) is not None

    def test_the_reason_says_what_to_do_about_it(self) -> None:
        """A refusal that does not say how to fix it costs the contestant a run."""
        reason = single_company.blocks_scoring(2)
        assert reason is not None
        assert "--agent-companies 1" in reason
        assert "2 contestant companies" in reason


class TestItIsAppliedWhenTheCountIsKnown:
    def test_the_session_start_path_checks_it(self) -> None:
        """The scenario cannot express this, so the check has to happen where the
        argument arrives."""
        import inspect

        from nttd.runtime.session_manager import SessionManager

        source = inspect.getsource(SessionManager.start_session)
        assert "blocks_scoring(agent_companies)" in source
        assert source.index("blocks_scoring") < source.index("scored_lock.scored")

    def test_recovery_applies_it_too(self) -> None:
        """_scored is stored from the scenario and the count that disqualified it lives
        in a different key, so a restart would otherwise re-score the session."""
        import inspect

        from nttd.runtime.session_manager import SessionManager

        source = inspect.getsource(SessionManager)
        recovery = source.split("Recovered session")[0].split("_apply_step_size(runtime, stored)")[0]
        assert "_agent_companies" in recovery


class TestWhatItDoesNotDo:
    def test_it_does_not_stop_the_session_running(self) -> None:
        """Unscored is not refused. Self-play still needs to work, and a run that
        cannot be ranked is still a run worth having."""
        source = (
            __import__("inspect").getsource(
                __import__("nttd.runtime.session_manager", fromlist=["x"]).SessionManager.start_session,
            )
        )
        blocked = source.split("blocks_scoring(agent_companies)")[1][:400]
        assert "raise" not in blocked, "a multi-company session must still start"

    def test_ai_opponents_do_not_count(self) -> None:
        """Idle AI slots are not contestants. Counting them would make every session
        with opponents unscoreable, which is the opposite of the intent."""
        import inspect

        from nttd.runtime.session_manager import SessionManager

        source = inspect.getsource(SessionManager.start_session)
        assert "blocks_scoring(ai_count)" not in source
        assert "blocks_scoring(ai_opponents)" not in source
