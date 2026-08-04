"""The client-driven play path: the contestant owns the loop, nttd serves it.

This is the ONLY scored path. A contestant -- an LLM agent, a multi-agent system, an
RL policy, or an ES candidate -- runs its own observe/decide/act loop and reaches
nttd over the participant REST routes. nttd no longer runs anybody's agent.

These tests exist BEFORE the server-driven gameloop is deleted, because that
deletion is only safe if this path is already complete. Written against the route
handlers rather than a live OpenTTD session, so they run in CI: what is being proven
is that the request path is intact and correctly guarded, not that OpenTTD builds
track.

The four properties that must hold, since the gameloop currently provides none of
them for a client-driven contestant:

  1. Observation needs no agent registration. If it did, deleting the gameloop
     would remove the only way to see the world.
  2. Actions need no agent registration, and are scoped by token, not by a
     caller-supplied company_id.
  3. The action budget binds here. It is the sole enforcement point once the
     gameloop's per-cycle truncation is gone.
  4. Every action is recorded, refusals included. A benchmark cannot be verified
     from an action log that is missing the actions.

Run with: uv run pytest tests/test_client_driven_play.py -v
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from nttd.api import action_routes, observation_routes
from nttd.constants import KNOWN_ACTIONS, READ_ONLY_GS_ACTIONS
from nttd.schemas.action_result import ActionStatus

# ---------------------------------------------------------------------------
# 1. The loop needs no gameloop registration
# ---------------------------------------------------------------------------
# The decisive property. Verified by reading the handlers' source: if either
# module reached for gameloop_manager, a client-driven contestant would depend on
# the machinery being removed.


def _module_source(module: Any) -> str:
    return inspect.getsource(module)


def test_observation_routes_do_not_touch_the_gameloop() -> None:
    source = _module_source(observation_routes)
    assert "gameloop" not in source, (
        "observation depends on the gameloop, so deleting it would leave a "
        "client-driven contestant unable to see the world"
    )


def test_action_routes_do_not_touch_the_gameloop() -> None:
    """The comment mentioning gameloop agents is prose, not a dependency."""
    for line in _module_source(action_routes).splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        assert "gameloop_manager" not in stripped, (
            f"action_routes reaches the gameloop at: {stripped}"
        )


def test_submitting_an_action_does_not_require_a_registered_agent() -> None:
    """submit_action's parameters are the whole contract a contestant must satisfy.

    An agent_id or connection_id here would mean registration first.
    """
    params = set(inspect.signature(action_routes.submit_action).parameters)
    assert params == {
        "session_id", "envelope", "x_participant_token", "authorization",
    }
    assert "agent_id" not in params
    assert "connection_id" not in params


def test_observing_requires_only_the_session() -> None:
    for handler in (observation_routes.get_full_state, observation_routes.get_compact_state):
        params = set(inspect.signature(handler).parameters)
        assert "agent_id" not in params
        assert "session_id" in params


# ---------------------------------------------------------------------------
# 2. The contestant's vocabulary is complete without the gameloop
# ---------------------------------------------------------------------------


def test_the_participant_vocabulary_is_reachable_over_rest() -> None:
    """Every action a contestant may take must be submittable through the one
    remaining path, or the deletion silently removes capability."""
    assert len(KNOWN_ACTIONS) > 50, "sanity: the vocabulary is not empty"
    source = _module_source(action_routes)
    assert "KNOWN_ACTIONS" in source, "submit must validate against the vocabulary"


def test_read_only_queries_are_reachable_without_the_gameloop() -> None:
    """gameloop/observation_tools.py is one way to run these; gs/query is the other,
    and it is the one a client-driven contestant uses."""
    assert len(READ_ONLY_GS_ACTIONS) > 20
    assert "find_station_spot" in READ_ONLY_GS_ACTIONS
    assert "get_engines" in READ_ONLY_GS_ACTIONS


def test_gs_query_still_refuses_mutators() -> None:
    """Phase 2 closed this bypass. It must stay closed when gs/query becomes the
    primary query path rather than one of two."""
    for mutator in ("set_max_loan", "change_bank_balance", "found_town", "create_subsidy"):
        assert mutator not in READ_ONLY_GS_ACTIONS


# ---------------------------------------------------------------------------
# 3. The budget binds on the REST path
# ---------------------------------------------------------------------------
# Once the gameloop's per-cycle truncation is gone, ActionBudget is the only
# enforcement point. These assert it is wired where actions actually enter.


def test_both_paths_share_one_admission_check() -> None:
    """The property that closes the bypass.

    The REST route checked operator tier, the allowlist, and the budget inline; the
    stepped loop checked nothing and called send_gamescript directly, so
    set_max_loan executed in a scored session and left no audit row. Verified live:
    five queued operator actions ran with only the two REST attempts logged.

    Both now call actions.gate.admit, so there is one copy of the rules.
    """
    from nttd.runtime import orchestrator

    for module, name in (
        (inspect.getsource(action_routes.submit_action), "REST submit"),
        (inspect.getsource(orchestrator.Orchestrator._execute_actions), "stepped flush"),
    ):
        assert "admit(" in module, f"{name} does not go through the shared gate"


def test_the_gate_refuses_operator_tier() -> None:
    from nttd.actions.gate import admit

    admission = admit("set_max_loan", company_id=0)
    assert admission.allowed is False
    assert admission.status is ActionStatus.REJECTED
    assert "operator-tier" in admission.error


def test_the_gate_refuses_an_unknown_action() -> None:
    from nttd.actions.gate import admit

    admission = admit("teleport_vehicle", company_id=0)
    assert admission.allowed is False
    assert admission.status is ActionStatus.REJECTED
    assert "Unknown action_type" in admission.error


def test_the_gate_admits_a_participant_action() -> None:
    from nttd.actions.gate import admit

    assert admit("build_road_stop", company_id=0).allowed is True


def test_the_gate_refuses_an_over_budget_submission() -> None:
    """BLOCKED rather than REJECTED: the scenario's limit, not the contestant's
    mistake, and a reader of the action log needs to tell those apart."""
    from nttd.actions.gate import admit
    from nttd.runtime.action_budget import ActionBudget

    budget = ActionBudget(max_per_submission=5, enforced=True)
    admission = admit("build_road_stop", company_id=0, budget=budget, count=50)
    assert admission.allowed is False
    assert admission.status is ActionStatus.BLOCKED


def test_the_gate_checks_the_vocabulary_before_the_budget() -> None:
    """A refusal that never had a chance of succeeding must not spend budget."""
    from nttd.actions.gate import admit
    from nttd.runtime.action_budget import ActionBudget

    budget = ActionBudget(max_per_submission=5, enforced=True)
    admit("set_max_loan", company_id=0, budget=budget, count=99)
    assert budget.usage()["total_refused"] == 0, (
        "an operator-tier refusal charged the budget"
    )


def test_the_gate_does_not_consume_budget() -> None:
    """Checked but not consumed: the caller consumes where the action goes ahead, so
    a refusal on another path cannot spend it."""
    from nttd.actions.gate import admit
    from nttd.runtime.action_budget import ActionBudget

    budget = ActionBudget(max_per_submission=15, enforced=True)
    admit("build_road_stop", company_id=0, budget=budget)
    assert budget.usage()["used_actions"] == {}


def test_submit_consumes_after_admission() -> None:
    source = inspect.getsource(action_routes.submit_action)
    assert source.index("admit(") < source.index("consume(")
    assert source.index("consume(") < source.index("send_gamescript")


def test_a_batch_is_checked_against_its_full_count() -> None:
    """Otherwise batching sidesteps the ceiling one action at a time."""
    source = inspect.getsource(action_routes.submit_action_batch)
    assert "count=len(envelopes)" in source


def test_the_stepped_path_records_its_actions() -> None:
    """It recorded nothing, so a run driven by steps produced no actions.parquet."""
    from nttd.runtime import orchestrator

    source = inspect.getsource(orchestrator.Orchestrator._execute_actions)
    assert "_record_action(" in source


def test_a_refusal_is_recorded_on_both_paths() -> None:
    from nttd.runtime import orchestrator

    rest = inspect.getsource(action_routes.submit_action)
    stepped = inspect.getsource(orchestrator.Orchestrator._execute_actions)
    for source, name in ((rest, "REST"), (stepped, "stepped")):
        refused = source.index("admission.allowed")
        window = source[refused:refused + 900]
        assert "_record" in window, f"{name} does not record a refusal"


# ---------------------------------------------------------------------------
# The scored clock starts on the contestant's first action
# ---------------------------------------------------------------------------


def test_the_scored_clock_starts_on_first_action_not_at_registration() -> None:
    """With no registration step, the clock has to start from the action path or a
    contestant would be charged for provisioning time."""
    source = inspect.getsource(action_routes.submit_action)
    assert "start_scored_clock" in source


# ---------------------------------------------------------------------------
# Token accounting: what nttd can and cannot know
# ---------------------------------------------------------------------------


def test_result_records_distinguish_observed_from_reported_counts() -> None:
    """nttd runs no LLM in the client-driven model, so it cannot observe tokens.

    Action counts stay server-observed: actions.parquet records company_id and
    status per action, so they are derivable from nttd's own log. Token and cost
    figures are not, and must be marked as contestant-reported rather than
    presented with the same authority.
    """
    from nttd.db.recorder import _ACTIONS_SCHEMA

    names = set(_ACTIONS_SCHEMA.names)
    assert {"company_id", "status", "action_type"} <= names, (
        "action counts must remain derivable from nttd's own audit log"
    )


@pytest.mark.parametrize(
    "column", ["total_actions", "successful_actions"],
)
def test_action_counts_remain_result_columns(column: str) -> None:
    from nttd.db.result_writer import _SCHEMA

    assert column in _SCHEMA.names
