"""An action whose parameters were put in the wrong place is refused, not silently emptied.

A step action is ``{"action": ..., "params": {...}}``. Written flat, every field beyond
``action`` used to be dropped without a word: ``params`` arrived empty and the GameScript
failed on the first field it read, answering "the index 'x' does not exist". That names
neither the mistake nor where the fields belonged, and it looks identical to genuinely
omitting a required argument. Two steps of a 31 step run were lost to it by hand.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nttd.schemas.step_result import StepRequest


def test_the_documented_shape_is_accepted() -> None:
    request = StepRequest(actions=[
        {"action": "build_rail_station", "params": {"x": 8, "y": 31, "direction": 0}},
    ])
    assert request.actions[0]["params"]["x"] == 8


def test_flat_parameters_are_refused_and_named() -> None:
    with pytest.raises(ValidationError) as caught:
        StepRequest(actions=[
            {"action": "build_rail_station", "x": 8, "y": 31, "direction": 0},
        ])
    message = str(caught.value)
    assert "direction" in message and "x" in message and "y" in message
    assert "params" in message


def test_the_refusal_says_which_action_was_wrong() -> None:
    """A batch is many actions, so the index and name have to be in the message."""
    with pytest.raises(ValidationError) as caught:
        StepRequest(actions=[
            {"action": "connect_rail", "params": {"from_x": 1, "from_y": 2}},
            {"action": "build_rail_depot", "x": 13, "y": 30},
        ])
    message = str(caught.value)
    assert "action 1" in message
    assert "build_rail_depot" in message


def test_an_action_with_no_parameters_is_fine() -> None:
    """Stepping with an empty batch, and actions that genuinely take nothing, still work."""
    assert StepRequest(actions=[]).actions == []
    assert StepRequest(actions=[{"action": "ping"}]).actions[0]["action"] == "ping"


def test_the_two_key_shape_is_accepted() -> None:
    """A caller that sends only action and params is admitted."""
    request = StepRequest(actions=[{"action": "buy_vehicle", "params": {"engine_id": 12}}])
    assert request.actions[0]["action"] == "buy_vehicle"


def test_an_action_may_name_itself_and_its_agent() -> None:
    """A caller that sets action_id gets it back on the result, and metadata reaches
    the action log. Both are optional, so the two-key shape above still passes."""
    request = StepRequest(actions=[{
        "action": "build_dock", "params": {"x": 1, "y": 2},
        "action_id": "crew_3:7", "metadata": {"participant_id": "crew_3"},
    }])
    assert request.actions[0]["action_id"] == "crew_3:7"
    assert request.actions[0]["metadata"]["participant_id"] == "crew_3"
