"""Compound builds that only partly succeed.

``connect_road``, ``connect_rail`` and ``build_path`` lay a whole route in one action.
They used to return ``success = true`` whatever happened, with the failures tucked into
a ``failed`` list inside the result. A segment that would not build leaves a gap, and a
gap means no route, so a broken line was indistinguishable from a working one to the
agent, the action log, and the route-completion report. An RL policy rewarded on action
success was being told the route worked.

The second half was ``ERR_ALREADY_BUILT`` counting as ``built``. That conflates two
different things: track already there means the route is connected, but nobody built it
and nobody paid for it. Reported as built, it inflated the apparent work of laying a
route over existing infrastructure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_GAMESCRIPT = Path(__file__).parent.parent / "ottd_config" / "game" / "nttd-gs" / "main.nut"


@pytest.fixture(scope="module")
def gamescript() -> str:
    return _GAMESCRIPT.read_text()


class TestTheGameScriptSeparatesBuiltFromAlreadyThere:
    def test_already_built_never_counts_as_built(self, gamescript: str) -> None:
        """Every site that saw ERR_ALREADY_BUILT used to increment the built counter."""
        assert 'ERR_ALREADY_BUILT") { built++; }' not in gamescript
        assert "else built++;" not in gamescript

    def test_it_is_counted_separately_instead(self, gamescript: str) -> None:
        assert gamescript.count("existing++") >= 8

    def test_an_already_connected_road_tile_is_not_built(self, gamescript: str) -> None:
        """AreRoadTilesConnected means the link is there. Nothing was laid or paid for."""
        assert "existing++; // Already connected" in gamescript

    def test_every_counter_is_declared_where_it_is_used(self, gamescript: str) -> None:
        """Squirrel does not catch an undeclared local until the line runs, so a missing
        declaration would present as a route build dying partway through."""
        for name in ("_BuildRoadPath", "_BuildRailPath", "CmdBuildPath"):
            body = _function_body(gamescript, name)
            if "existing++" in body:
                assert "local existing = 0;" in body, name


class TestABrokenRouteIsNotASuccess:
    @pytest.mark.parametrize("function", ["CmdConnectRoad", "CmdConnectRail", "CmdBuildPath"])
    def test_success_depends_on_whether_anything_failed(
        self, gamescript: str, function: str,
    ) -> None:
        body = _function_body(gamescript, function)
        assert "success = complete" in body, f"{function} still reports unconditional success"
        assert "return { success = true, result" not in body

    @pytest.mark.parametrize("function", ["CmdConnectRoad", "CmdConnectRail", "CmdBuildPath"])
    def test_a_partial_route_says_how_much_is_missing(
        self, gamescript: str, function: str,
    ) -> None:
        assert "_PartialError" in _function_body(gamescript, function)

    def test_the_message_names_the_first_failure(self, gamescript: str) -> None:
        """The failed list can be long and the first reason is usually the reason for
        all of them, so an agent should not have to parse the list to learn anything."""
        body = _function_body(gamescript, "_PartialError")
        for part in ("failed.len()", "first.x", "first.error"):
            assert part in body

    @pytest.mark.parametrize("function", ["CmdConnectRoad", "CmdConnectRail", "CmdBuildPath"])
    def test_the_partial_result_still_comes_back(
        self, gamescript: str, function: str,
    ) -> None:
        """A failed compound build still changed the world. Returning only an error
        would leave the agent unable to tell what it now owns."""
        body = _function_body(gamescript, function)
        assert "status = complete" in body
        assert "built = built" in body or "built = build.built" in body


class TestTheFailureReachesThePythonSide:
    def test_a_partial_build_is_recorded_as_failed(self) -> None:
        """The route-completion report and the plots count status == success. With the
        old unconditional success they counted a broken route as a finished one."""
        import inspect

        from nttd.api import action_routes

        source = inspect.getsource(action_routes.submit_action)
        assert 'gs_result.get("success")' in source

    def test_what_was_built_survives_the_failure(self) -> None:
        """Recording nothing would understate a half-laid route: the track exists and
        was paid for."""
        import inspect

        from nttd.api import action_routes

        source = inspect.getsource(action_routes.submit_action)
        partial = source.split("else:")[-1]
        assert "changed_entities=partial" in partial

    def test_the_tracker_accepts_a_result_alongside_a_failure(self) -> None:
        import inspect

        from nttd.actions.tracker import ActionTracker

        signature = inspect.signature(ActionTracker.update_result)
        assert "changed_entities" in signature.parameters


def _function_body(source: str, name: str) -> str:
    """One Squirrel function, matched by brace depth."""
    match = re.search(rf"function {re.escape(name)}\s*\(", source)
    assert match, f"{name} not found in the GameScript"
    start = source.index("{", match.end() - 1)
    depth, index = 1, start + 1
    while index < len(source) and depth:
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        index += 1
    return source[start:index]
