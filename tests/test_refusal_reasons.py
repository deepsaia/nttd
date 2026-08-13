"""Turning a refusal into something an agent can act on.

OpenTTD maps a failure to a named ScriptError only when the underlying CommandCost carries
a string it recognises. Everything else arrives as ERR_UNKNOWN, code 1, category none,
which is most refusals in practice and is the one answer nothing can be done with.

Measured cost of that during hand-play: a run spent two of its five actions re-submitting
a build onto its own station, and another lost an action to a rail type mismatch it had no
way to see, because get_rail_types cannot name the types either.

So the GameScript inspects the world on the failure path and sends a `reason`. These tests
cover the Python half: that the reason leads, that the game's own wording is not lost, and
that a reply without one is unchanged.
"""

from __future__ import annotations

from nttd.actions.gs_reply import result_from_reply
from nttd.schemas.action_result import ActionStatus


def test_a_reason_leads_and_the_games_wording_follows() -> None:
    """Both halves matter: the reason is what to act on, the code is what to match on."""
    out = result_from_reply("a1", {
        "success": False,
        "error": "ERR_UNKNOWN",
        "error_code": 1,
        "reason": "a station already occupies this tile",
    })
    assert out.status is ActionStatus.FAILED
    assert out.error.startswith("a station already occupies this tile")
    assert "ERR_UNKNOWN" in out.error


def test_a_refusal_without_a_reason_is_left_exactly_as_it_was() -> None:
    """Most handlers do not pass a hint yet, and must keep working untouched."""
    out = result_from_reply("a1", {
        "success": False, "error": "ERR_AREA_NOT_CLEAR", "error_code": 260,
    })
    assert out.error == "ERR_AREA_NOT_CLEAR"


def test_the_error_code_survives_the_rewording() -> None:
    """nttd's own precondition failures carry no code, and that is how they are told
    apart from OpenTTD's. Adding a reason must not disturb that."""
    out = result_from_reply("a1", {
        "success": False, "error": "ERR_UNKNOWN", "error_code": 1,
        "error_category": 0, "reason": "this tile already carries rail",
    })
    assert out.error_code == 1
    assert out.error_name == "ERR_UNKNOWN"


def test_a_reason_with_no_game_error_stands_alone() -> None:
    out = result_from_reply("a1", {"success": False, "reason": "the balance is too low"})
    assert out.error == "the balance is too low"


def test_a_reason_identical_to_the_error_is_not_repeated() -> None:
    out = result_from_reply("a1", {
        "success": False, "error": "same thing", "reason": "same thing",
    })
    assert out.error == "same thing"


def test_a_success_is_untouched_by_any_of_this() -> None:
    out = result_from_reply("a1", {
        "success": True, "result": {"station_id": 0, "tile": [76, 184]},
    })
    assert out.status is ActionStatus.SUCCESS
    assert out.changed_entities["station_id"] == 0


def test_a_partial_build_keeps_its_status_and_what_it_managed() -> None:
    """A compound build that laid part of a route is not a plain failure: the world moved
    and was paid for."""
    out = result_from_reply("a1", {
        "success": False,
        "error": "7 of 36 segments failed",
        "result": {"status": "partial", "built": 29},
        "reason": "this tile already carries rail",
    })
    assert out.status is ActionStatus.PARTIAL
    assert out.changed_entities["built"] == 29
    assert out.error.startswith("this tile already carries rail")
