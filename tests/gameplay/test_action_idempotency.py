"""Resending an action must not do it twice.

``connect_road`` runs A* inside the GameScript and is given a 120-second timeout, which
is long enough for a proxy or an impatient client to give up and resend. Without a key,
the second request lays the route again: the tiles are already there so most segments
come back ERR_ALREADY_BUILT, but the parts that had failed get retried and anything the
first attempt did not reach gets built and charged a second time.

``action_id`` is supplied by the caller and was already stored per action, so it is the
key. Nothing new had to be invented, only used.
"""

from __future__ import annotations

from typing import Any

import pytest

from nttd.actions.tracker import ActionTracker
from nttd.api.action_routes import _already_settled
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionStatus


class FakeRuntime:
    """Just enough runtime for the lookup."""

    def __init__(self) -> None:
        self.action_tracker = ActionTracker()


def _submitted(runtime: FakeRuntime, action_id: str) -> ActionEnvelope:
    envelope = ActionEnvelope(
        action_id=action_id, action_type="connect_road", parameters={}, company_id=0,
    )
    runtime.action_tracker.submit(envelope)
    return envelope


class TestASettledActionIsNotRerun:
    @pytest.mark.parametrize(
        "status",
        [
            ActionStatus.SUCCESS,
            ActionStatus.PARTIAL,
            ActionStatus.FAILED,
            ActionStatus.REJECTED,
            ActionStatus.BLOCKED,
        ],
    )
    def test_every_terminal_status_is_replayed(self, status: ActionStatus) -> None:
        runtime = FakeRuntime()
        _submitted(runtime, "a1")
        runtime.action_tracker.update_result("a1", status, "whatever happened")

        settled = _already_settled(runtime, "a1")
        assert settled is not None
        assert settled.status == status

    def test_the_original_result_comes_back_unchanged(self) -> None:
        """A retry should learn what happened the first time, not a fresh attempt at it."""
        runtime = FakeRuntime()
        _submitted(runtime, "a1")
        runtime.action_tracker.update_result(
            "a1", ActionStatus.PARTIAL, "2 of 24 segments failed",
            changed_entities={"built": 19, "existing": 3},
        )

        settled = _already_settled(runtime, "a1")
        assert settled is not None
        assert settled.changed_entities == {"built": 19, "existing": 3}
        assert settled.error == "2 of 24 segments failed"


class TestAnUnsettledActionIsNot:
    @pytest.mark.parametrize("status", [ActionStatus.PENDING, ActionStatus.EXECUTING])
    def test_an_action_still_running_is_not_replayed(self, status: ActionStatus) -> None:
        """A resend while the first attempt is in flight is a different problem.
        Answering it from the tracker would report a result that does not exist yet,
        which is worse than doing the work twice: it would be a made-up answer.
        """
        runtime = FakeRuntime()
        _submitted(runtime, "a1")
        runtime.action_tracker.update_result("a1", status)

        assert _already_settled(runtime, "a1") is None

    def test_an_unknown_action_is_not_replayed(self) -> None:
        assert _already_settled(FakeRuntime(), "never-seen") is None

    def test_a_different_id_runs_normally(self) -> None:
        """Only a repeat of the same id is a retry. Two identical actions with different
        ids are two actions, and a contestant laying the same road twice on purpose is
        entitled to do so."""
        runtime = FakeRuntime()
        _submitted(runtime, "a1")
        runtime.action_tracker.update_result("a1", ActionStatus.SUCCESS)

        assert _already_settled(runtime, "a2") is None


def test_the_route_checks_before_it_dispatches() -> None:
    """The guard has to run before the GameScript call, or it guards nothing."""
    import inspect

    from nttd.api.action_routes import submit_action

    source = inspect.getsource(submit_action)
    assert source.index("_already_settled") < source.index("send_gamescript")


def test_the_recorded_history_is_not_lost_to_trimming(monkeypatch: Any) -> None:
    """The tracker keeps a bounded history. An id evicted from it is no longer a key,
    so this documents the limit rather than pretending it does not exist: a retry of
    something more than max_history actions ago will run again.
    """
    runtime = FakeRuntime()
    runtime.action_tracker = ActionTracker(max_history=2)
    for index in range(3):
        envelope = ActionEnvelope(
            action_id=f"a{index}", action_type="build_dock", parameters={}, company_id=0,
        )
        runtime.action_tracker.submit(envelope)
        runtime.action_tracker.update_result(f"a{index}", ActionStatus.SUCCESS)

    assert _already_settled(runtime, "a0") is None
    assert _already_settled(runtime, "a2") is not None
