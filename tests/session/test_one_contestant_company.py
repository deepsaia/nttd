"""A session holds one contestant company, and refuses to start with more.

This used to be a scoring rule: several contestants were allowed and the run was merely
left unscored. That was the wrong shape. A contestant learned at submission time that a
finished run had never been scoreable, and the machinery to synchronise several
companies stepping one clock existed to serve a case no board would ever accept.

So it is refused at the door instead. What was ``single_company.blocks_scoring`` and its
tests are gone, replaced by these.

Several agents playing *together* are unaffected: a multi-agent entry drives one company,
and its orchestrator decides what that company does before submitting a step. So is
``num_ai_companies``, which creates idle non-contestant slots that do not compete.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nttd.constants import MAX_CONTESTANT_COMPANIES


class TestTheBound:
    def test_it_is_one(self) -> None:
        assert MAX_CONTESTANT_COMPANIES == 1


class TestTheApiRefuses:
    @pytest.fixture
    def client(self) -> TestClient:
        from nttd.api.app import app

        return TestClient(app)

    @pytest.mark.parametrize("count", [0, 1])
    def test_none_or_one_is_accepted_by_the_schema(self, count: int) -> None:
        """Zero is a session nobody plays through the participant routes, which is what
        a human entry recorded over CMD_LOGGING looks like."""
        from nttd.api.admin_routes import StartSessionRequest

        assert StartSessionRequest(agent_companies=count).agent_companies == count

    @pytest.mark.parametrize("count", [2, 3, 15])
    def test_more_than_one_is_rejected_by_the_schema(self, count: int) -> None:
        from pydantic import ValidationError

        from nttd.api.admin_routes import StartSessionRequest

        with pytest.raises(ValidationError):
            StartSessionRequest(agent_companies=count)

    def test_the_route_answers_422_rather_than_starting(self, client: TestClient) -> None:
        """Refused before anything spawns. The old rule let the session start and only
        withheld the score, so the process, the ports and the map all existed for a run
        that could never be submitted."""
        response = client.post(
            "/v1/operator/admin/sessions/ses_nonexistent/start",
            json={"mode": "newgame", "agent_companies": 2},
        )
        assert response.status_code == 422


class TestTheCliRefuses:
    def _run(self, count: int) -> object:
        from nttd.cli.app import app

        return CliRunner().invoke(
            app, ["session", "start", "-s", "ses_x", "--agent-companies", str(count)],
        )

    def _said(self, count: int) -> str:
        """The output with its wrapping removed. rich breaks lines to fit the terminal,
        so a phrase can arrive split and an assertion on it fails for no real reason."""
        return " ".join(self._run(count).output.split())

    def test_more_than_one_exits_non_zero(self) -> None:
        result = self._run(2)
        assert result.exit_code == 1

    def test_it_says_what_to_do_instead(self) -> None:
        """A bound quoted back by a validator tells a contestant they were wrong. This
        should tell them how multi-agent play actually works, since wanting two
        companies usually means wanting two agents."""
        said = self._said(2)
        assert "holds 1 contestant company" in said
        assert "--agent-companies 1" in said
        assert "--ai-opponents" in said

    def test_it_refuses_before_asking_the_server(self) -> None:
        """Caught by this test: the check sat after check_server, so an invalid argument
        reported "cannot reach nttd server" and exited 1 for the wrong reason. The
        argument is wrong whether or not anything is running."""
        assert "cannot reach" not in self._said(2).lower()


class TestWhatIsUnaffected:
    def test_the_scoring_guard_is_gone(self) -> None:
        """It guarded against a session that can no longer be started, so it was
        unreachable rather than wrong."""
        with pytest.raises(ModuleNotFoundError):
            import nttd.config.single_company  # noqa: F401

    def test_the_parallel_env_is_gone(self) -> None:
        """It drove several companies in one process, which is the shape that no longer
        exists."""
        with pytest.raises(ModuleNotFoundError):
            import nttd.rl.multi_env  # noqa: F401

    def test_the_single_company_env_remains(self) -> None:
        """One policy, one company, one session. RL and ES spawn their own sessions."""
        from nttd.rl.env import NttdEnv

        assert NttdEnv is not None
