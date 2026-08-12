"""The scenario decides whether a run is stepped, not the contestant.

The two modes measure different things, and the difference is the point of having both. In
real time, thinking costs game days, so speed is part of what is scored. In stepped play the
world is paused between steps and deliberation is free, which is what makes a language model
policy comparable with a trained one on decision quality rather than latency.

Before this guard, a scenario declaring async_realtime accepted POST /step/reset and became
stepped and paused, with the contestant holding the clock. Worse, the 409 from POST /step
recommended exactly that, so it was reachable by following an error message rather than by
attacking anything.

Verified live at the time: reset returned 200 and the snapshot came back with
mode == "stepped" and paused == true on a session created from a real-time config.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from nttd.api.control_routes import _require_stepped_scenario
from nttd.runtime.step_errors import ScenarioIsNotStepped
from nttd.schemas.game import RuntimeMode


class _Runtime:
    """Just the two fields the guard reads."""

    def __init__(self, declared: str, world_mode: str = "") -> None:
        self.runtime_mode = declared
        self.world = type("W", (), {"game": type("G", (), {"mode": world_mode})()})()


def _refusal(declared: str) -> HTTPException | None:
    try:
        _require_stepped_scenario(_Runtime(declared))
    except HTTPException as exc:
        return exc
    return None


# ----------------------------------------------------------------------


def test_a_real_time_scenario_cannot_be_stepped() -> None:
    refusal = _refusal(RuntimeMode.ASYNC_REALTIME)
    assert refusal is not None
    assert refusal.status_code == 409


def test_a_heartbeat_scenario_cannot_be_stepped_either() -> None:
    """The server owns the loop there, so a contestant stepping it would fight it."""
    assert _refusal(RuntimeMode.HEARTBEAT) is not None


def test_a_stepped_scenario_is_allowed() -> None:
    assert _refusal(RuntimeMode.STEPPED) is None


def test_a_session_with_no_declared_mode_is_left_alone() -> None:
    """A session created without a scenario declares nothing, and refusing it would break
    the direct session API that tests and manual play use."""
    assert _refusal("") is None


def test_the_refusal_says_what_to_do_instead() -> None:
    """An agent told only no retries forever, which is the standard the action gate set."""
    refusal = _refusal(RuntimeMode.ASYNC_REALTIME)
    assert "/actions/submit" in refusal.detail
    assert "real time" in refusal.detail


def test_the_refusal_does_not_recommend_the_conversion() -> None:
    """The old 409 recommended POST /step/reset, which was the conversion itself."""
    refusal = _refusal(RuntimeMode.ASYNC_REALTIME)
    assert "/step/reset" not in refusal.detail


def test_the_check_reads_the_declared_mode_not_the_world_state() -> None:
    """A conversion changes the world's mode. Reading that would let the second call
    through on the strength of the first, which is the whole hole."""
    runtime = _Runtime(RuntimeMode.ASYNC_REALTIME, world_mode=RuntimeMode.STEPPED)
    with pytest.raises(HTTPException):
        _require_stepped_scenario(runtime)


def test_the_error_names_the_mode_it_found() -> None:
    """So an operator reading a log can tell which scenario was misconfigured."""
    assert "async_realtime" in str(ScenarioIsNotStepped("async_realtime"))
