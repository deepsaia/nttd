"""Telling one kind of failure from another.

The error field carried everything interchangeably: OpenTTD error names, nttd's own
sentences, and Squirrel exception text. A caller could not tell "the game said no" from
"nttd would not send it", and the only way to act on a failure was to pattern-match a
string that had no promise of stability. RL and ES need a discrete signal.

Two integers now come back from the GameScript when OpenTTD is the one refusing, and the
names for them are read from the build rather than written here: `GSError.GetLastError()`
returns 257 and the dump says that is `ERR_NOT_ENOUGH_CASH`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nttd.actions.gs_reply import result_from_reply
from nttd.config import error_codes
from nttd.schemas.action_result import ActionStatus

_GAMESCRIPT = Path(__file__).parent.parent / "ottd_config" / "game" / "nttd-gs" / "main.nut"


class TestTheNamesComeFromTheBuild:
    """Not from a table typed here. These change between OpenTTD versions."""

    @pytest.mark.parametrize(
        ("code", "name"),
        [
            (257, "ERR_NOT_ENOUGH_CASH"),
            (259, "ERR_ALREADY_BUILT"),
            (264, "ERR_LAND_SLOPED_WRONG"),
            (4, "ERR_PRECONDITION_INVALID_COMPANY"),
        ],
    )
    def test_a_code_resolves_to_its_constant(self, code: int, name: str) -> None:
        assert error_codes.error_name(code) == name

    @pytest.mark.parametrize(
        ("category", "name"), [(1, "general"), (6, "tile"), (8, "rail"), (9, "road")],
    )
    def test_a_category_resolves_to_a_bare_word(self, category: int, name: str) -> None:
        """`ERR_CAT_TILE` is noise when the column is already called category."""
        assert error_codes.category_name(category) == name

    def test_the_rail_category_is_not_the_width_marker(self) -> None:
        """ERR_CAT_BIT_SIZE shares the value 8 with ERR_CAT_RAIL and sorts first, so a
        naive mapping reports every rail failure as category "bit_size"."""
        assert error_codes.category_name(8) == "rail"

    def test_an_unknown_number_resolves_to_nothing(self) -> None:
        """Better empty than a confident wrong name, which is what a stale hand-written
        table would give after an OpenTTD upgrade."""
        assert error_codes.error_name(9999) == ""
        assert error_codes.category_name(9999) == ""

    def test_it_survives_a_missing_dump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing enums.json should degrade to numbers, not stop a game."""
        import importlib

        monkeypatch.setattr(error_codes, "ENUMS_PATH", Path("/nonexistent/enums.json"))
        reloaded = importlib.reload(error_codes)
        assert reloaded.error_name(257) in ("", "ERR_NOT_ENOUGH_CASH")
        importlib.reload(error_codes)


class TestAnOpenTTDRefusalIsToldApartFromOurs:
    def test_the_game_refusing_carries_a_code(self) -> None:
        result = result_from_reply("a1", {
            "success": False,
            "error": "ERR_NOT_ENOUGH_CASH",
            "error_code": 257,
            "error_category": 1,
        })
        assert result.status == ActionStatus.FAILED
        assert result.error_code == 257
        assert result.error_name == "ERR_NOT_ENOUGH_CASH"
        assert result.error_category == "general"

    def test_nttd_refusing_carries_none(self) -> None:
        """The absence of a code is what identifies our own precondition failures.
        Inventing one would make them indistinguishable from the game's."""
        result = result_from_reply("a1", {
            "success": False, "error": "Need tile or x,y",
        })
        assert result.error == "Need tile or x,y"
        assert result.error_code is None
        assert result.error_name == ""
        assert result.error_category == ""

    def test_a_success_carries_no_error_at_all(self) -> None:
        result = result_from_reply("a1", {"success": True, "result": {"tile": 4096}})
        assert result.status == ActionStatus.SUCCESS
        assert result.error == ""
        assert result.error_code is None


class TestTheGameScriptSendsThem:
    @pytest.fixture(scope="class")
    def gamescript(self) -> str:
        return _GAMESCRIPT.read_text()

    def test_refusals_go_through_one_helper(self, gamescript: str) -> None:
        """96 sites returned the bare string. Left as they were, each would have needed
        remembering separately."""
        assert "function _Refused()" in gamescript
        assert "return { success = false, error = GSError.GetLastErrorString() };" not in gamescript

    def test_the_helper_reads_all_three(self, gamescript: str) -> None:
        body = _function_body(gamescript, "_Refused")
        for call in ("GetLastErrorString()", "GetLastError()", "GetErrorCategory()"):
            assert call in body

    def test_the_sender_forwards_them(self, gamescript: str) -> None:
        """Set on the result and dropped by the sender, they would never leave the
        GameScript, and every test above would still pass."""
        body = _function_body(gamescript, "_SendResponse")
        assert 'rawset("error_code"' in body
        assert 'rawset("error_category"' in body

    def test_a_failed_segment_carries_its_code(self, gamescript: str) -> None:
        """This matters most inside a compound build: a route that ran out of money is
        a different problem from one that hit a slope, and a policy should not have to
        match strings to tell them apart."""
        segments = [
            line for line in gamescript.splitlines()
            if "failed.append({" in line and "error = err" in line
        ]
        assert segments, "no failed-segment sites found, so this asserts nothing"
        assert all("error_code" in line for line in segments)


class TestBothExecutionPathsAgree:
    """The REST submission and the stepped flush each had their own copy of this
    mapping, which is how the stepped path came to know nothing about partial builds
    while the other did. The same divergence had already happened with admission."""

    def test_neither_path_maps_a_reply_itself(self) -> None:
        import inspect

        from nttd.api import action_routes
        from nttd.runtime import orchestrator

        for module in (action_routes, orchestrator):
            source = inspect.getsource(module)
            assert "result_from_reply" in source, module.__name__

    def test_the_stepped_path_reports_partial_too(self) -> None:
        import inspect

        from nttd.runtime import orchestrator

        source = inspect.getsource(orchestrator)
        assert 'result.get("success")' not in source, (
            "the stepped path is reading the reply itself again"
        )


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"function {re.escape(name)}\s*\(", source)
    assert match, f"{name} not found"
    start = source.index("{", match.end() - 1)
    depth, index = 1, start + 1
    while index < len(source) and depth:
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        index += 1
    return source[start:index]
