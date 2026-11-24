"""Reading the moves an agent sent, and naming each command."""

from __future__ import annotations

from nttd.mcp.moves import MOVES_FORMAT_HINT, coerce_flag, coerce_params, name_commands, read_moves


def test_params_may_arrive_as_an_object_a_json_string_or_nothing() -> None:
    assert coerce_params({"area": 100}) == {"area": 100}
    assert coerce_params('{"area": 100}') == {"area": 100}
    assert coerce_params(None) == {}
    assert coerce_params("  ") == {}
    assert coerce_params("not json") is None
    assert coerce_params("[1, 2]") is None
    assert coerce_params(5) is None


def test_flags_may_arrive_as_words() -> None:
    assert coerce_flag("true") and coerce_flag(" Yes ") and coerce_flag("1")
    assert not coerce_flag("false") and not coerce_flag("0") and not coerce_flag("")
    assert coerce_flag(True) and not coerce_flag(None)


def test_moves_may_arrive_as_a_list_an_object_or_a_json_string() -> None:
    one = {"command": "set_loan", "parameters": {"amount": 5}}
    assert read_moves([one]) == ([one], None)
    assert read_moves(one) == ([one], None)
    assert read_moves('[{"command": "set_loan", "parameters": "{\\"amount\\": 5}"}]') == ([one], None)
    assert read_moves(['{"command": "set_loan", "parameters": {"amount": 5}}']) == ([one], None)
    assert read_moves([{"command": "ping"}]) == ([{"command": "ping", "parameters": {}}], None)


def test_an_empty_input_is_no_moves() -> None:
    assert read_moves(None) == ([], None)
    assert read_moves([]) == ([], None)
    assert read_moves("  ") == ([], None)


def test_an_unreadable_input_returns_the_hint_and_no_moves() -> None:
    assert read_moves("not json") == ([], MOVES_FORMAT_HINT)
    assert read_moves(42) == ([], MOVES_FORMAT_HINT)
    assert read_moves([{"parameters": {}}]) == ([], MOVES_FORMAT_HINT)
    assert read_moves([{"command": "set_loan", "parameters": "oops"}]) == ([], MOVES_FORMAT_HINT)
    assert read_moves(["not json"]) == ([], MOVES_FORMAT_HINT)


class Typed:
    def __init__(self, command: object, parameters: dict) -> None:
        self.command = command
        self.parameters = parameters


class Member:
    value = "set_loan"


def test_typed_moves_from_a_schema_model_are_read_too() -> None:
    moves, error = read_moves([Typed(Member(), {"amount": 5})])
    assert error is None
    assert moves == [{"command": "set_loan", "parameters": {"amount": 5}}]


def test_named_commands_carry_a_unique_id_and_the_agent_tag() -> None:
    moves = [{"command": "set_loan", "parameters": {"amount": 5}}, {"command": "ping", "parameters": {}}]
    named = name_commands(moves, "crew_3", 7, "run_1")
    assert [c["action_id"] for c in named] == ["run_1:crew_3:7", "run_1:crew_3:8"]
    assert {c["agent_tag"] for c in named} == {"crew_3"}
    assert named[0]["command"] == "set_loan" and named[0]["parameters"] == {"amount": 5}
    assert name_commands([], "crew_3", 0, "run_1") == []


def test_unknown_move_fields_do_not_silently_become_empty_parameters() -> None:
    moves, error = read_moves([{"command": "set_loan", "params": {"amount": 5}}])
    assert moves == []
    assert "Unknown move fields: params" in error
    assert '"parameters"' in error
