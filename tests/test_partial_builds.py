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
        declaration would present as a route build dying partway through.

        Asked of every function rather than a named few, and matched on the declaration
        rather than one spelling of it: `local existing = 0;` and
        `local built = 0, existing = 0;` are the same thing.
        """
        undeclared = [
            name
            for name, body in _function_bodies(gamescript).items()
            if "existing++" in body and not re.search(r"local [^;]*\bexisting\s*=", body)
        ]
        assert undeclared == []


class TestNoCompoundBuilderIsMissed:
    """Written after the first pass missed one.

    The original tests named the three builders I knew about, so they passed while
    CmdBuildRoadLine still reported unconditional success and still counted
    ERR_ALREADY_BUILT as built. Its failure branch is written on a single line, which is
    why a search for the multi-line shape did not find it.

    These ask the question generally instead: find every function that collects failures,
    and hold all of them to the rule.
    """

    # The one deliberate exception. A train with fewer wagons than asked for is still a
    # train: it exists, it has an id, and it can be sent somewhere. That is unlike a road
    # with a gap, which is not a road. Listed here so the exemption is a decision rather
    # than an oversight, and so a second one cannot appear silently.
    _NOT_A_ROUTE = {"CmdBuildTrain"}

    def test_every_builder_that_collects_failures_reports_them(
        self, gamescript: str,
    ) -> None:
        offenders = [
            name
            for name, body in _function_bodies(gamescript).items()
            if "failed" in body
            and re.search(r"return \{ success = true[^;]*failed", body, re.S)
            and name not in self._NOT_A_ROUTE
        ]
        assert offenders == [], (
            f"{offenders} report success while carrying failures, which makes a broken "
            f"result indistinguishable from a working one"
        )

    def test_no_builder_counts_already_built_as_built(self, gamescript: str) -> None:
        """Checked line by line rather than by shape, because the two sites that were
        missed differ from the others only in their formatting."""
        offenders = [
            line.strip()
            for line in gamescript.splitlines()
            if "ERR_ALREADY_BUILT" in line and "built++" in line
        ]
        assert offenders == []

    def test_the_exemption_still_applies(self, gamescript: str) -> None:
        """If CmdBuildTrain stops being about a vehicle that exists regardless, the
        exemption above needs revisiting rather than silently continuing to hold."""
        body = _function_bodies(gamescript)["CmdBuildTrain"]
        assert "vehicle_id = vid" in body
        assert "wagons_failed" in body


# CmdBuildRoadLine was the fourth name here until build_rail_track was wired. It was
# deleted rather than fixed a second time: a straight run of road is build_path with a
# generated list, and it was the handler no case ever dispatched, so the rule it was
# being held to could not be reached from outside the Squirrel anyway. The general test
# below, TestNoCompoundBuilderIsMissed, is what keeps its replacement honest.


class TestABrokenRouteIsNotASuccess:
    @pytest.mark.parametrize(
        "function", ["CmdConnectRoad", "CmdConnectRail", "CmdBuildPath"],
    )
    def test_success_depends_on_whether_anything_failed(
        self, gamescript: str, function: str,
    ) -> None:
        body = _function_body(gamescript, function)
        assert "success = complete" in body, f"{function} still reports unconditional success"
        assert "return { success = true, result" not in body

    @pytest.mark.parametrize(
        "function", ["CmdConnectRoad", "CmdConnectRail", "CmdBuildPath"],
    )
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

    @pytest.mark.parametrize(
        "function", ["CmdConnectRoad", "CmdConnectRail", "CmdBuildPath"],
    )
    def test_the_partial_result_still_comes_back(
        self, gamescript: str, function: str,
    ) -> None:
        """A failed compound build still changed the world. Returning only an error
        would leave the agent unable to tell what it now owns."""
        body = _function_body(gamescript, function)
        assert "status = complete" in body
        assert "built = built" in body or "built = build.built" in body


class TestTheFailureReachesThePythonSide:
    """Exercised through the mapping rather than by reading the route's source.

    These used to grep submit_action for the expressions it happened to contain, which
    broke the moment the mapping moved into a shared function even though the behaviour
    was identical. Calling it says the same thing and survives being tidied.
    """

    def test_a_partial_build_is_not_a_success(self) -> None:
        """The route-completion report and the plots count status == success. Under the
        old unconditional success they counted a broken route as a finished one."""
        from nttd.actions.gs_reply import result_from_reply
        from nttd.schemas.action_result import ActionStatus

        result = result_from_reply("a1", {
            "success": False,
            "error": "2 of 24 segments failed, first at (41,55): ERR_LAND_SLOPED_WRONG",
            "result": {"status": "partial", "built": 19, "existing": 3, "failed": [{}, {}]},
        })
        assert result.status == ActionStatus.PARTIAL
        assert result.status != ActionStatus.SUCCESS

    def test_what_was_built_survives_the_failure(self) -> None:
        """Recording nothing would understate a half-laid route: the track exists and
        was paid for."""
        from nttd.actions.gs_reply import result_from_reply

        result = result_from_reply("a1", {
            "success": False,
            "error": "partial",
            "result": {"status": "partial", "built": 19, "existing": 3},
        })
        assert result.changed_entities["built"] == 19
        assert result.changed_entities["existing"] == 3

    def test_an_outright_refusal_is_still_failed(self) -> None:
        """Only a compound build reports partial. A dock that would not build is a
        plain refusal and must not be softened into one."""
        from nttd.actions.gs_reply import result_from_reply
        from nttd.schemas.action_result import ActionStatus

        result = result_from_reply("a1", {
            "success": False, "error": "ERR_SITE_UNSUITABLE", "error_code": 266,
        })
        assert result.status == ActionStatus.FAILED

    def test_the_tracker_accepts_a_result_alongside_a_failure(self) -> None:
        import inspect

        from nttd.actions.tracker import ActionTracker

        signature = inspect.signature(ActionTracker.update_result)
        assert "changed_entities" in signature.parameters


def _function_bodies(source: str) -> dict[str, str]:
    """Every Squirrel function in the GameScript, keyed by name."""
    bodies: dict[str, str] = {}
    for match in re.finditer(r"function (\w+)\s*\(", source):
        start = source.index("{", match.end() - 1)
        depth, index = 1, start + 1
        while index < len(source) and depth:
            depth += {"{": 1, "}": -1}.get(source[index], 0)
            index += 1
        bodies[match.group(1)] = source[start:index]
    return bodies


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


class TestBuildPathDoesNotSkipWhatItCannotDo:
    """The silent no-op, pinned.

    `build_path(transport_type="water")` returned success with built = 0. Two causes,
    both in this handler: anything not "rail" was treated as road, and any step action
    with no case fell through to a bare `skipped++`. A water path is made of canal steps,
    so every one was skipped and the reply said the route was laid.

    Verified live after the fix: an unknown transport_type is refused by name, a canal
    step builds, and an unknown step action comes back as a partial with the reason.
    """

    def _handler(self, gamescript: str) -> str:
        start = gamescript.index("function CmdBuildPath(p)")
        end = gamescript.index("function CmdDemolishTile(p)")
        return gamescript[start:end]

    def test_an_unknown_transport_type_is_refused(self, gamescript: str) -> None:
        body = self._handler(gamescript)
        assert 'transport_type must be rail, road or water' in body

    def test_water_is_a_transport_type_it_knows(self, gamescript: str) -> None:
        body = self._handler(gamescript)
        assert 'is_water' in body
        assert "GSMarine.BuildCanal" in body
        assert "GSMarine.BuildLock" in body

    def test_an_unknown_step_action_is_a_failure_not_a_skip(self, gamescript: str) -> None:
        """The root cause. A handler that quietly passes over what it does not
        understand reports success for having done nothing."""
        body = self._handler(gamescript)
        assert "does not know the step action" in body
        # The bare fall-through that used to end the loop is gone.
        assert not body.rstrip().endswith("skipped++;\n    }")

    def test_water_does_not_set_a_road_type(self, gamescript: str) -> None:
        """Treating water as road also set the current road type, which is meaningless
        and was a symptom of the same defaulting."""
        body = self._handler(gamescript)
        assert "else if (!is_water) GSRoad.SetCurrentRoadType" in body


class TestTerrainReadsAreBounded:
    """Reading a whole map is not a reasonable request at any size.

    It defaulted to the entire map: 256x256 measured 524 KB and 7.2 seconds, roughly
    389,000 tokens. At 512x512 the reply outran gs_query's timeout and came back as a
    bare failure. The cap is on TILES rather than map size, so one rule holds everywhere
    and no size has to be forbidden.
    """

    def _handler(self, gamescript: str) -> str:
        start = gamescript.index("function CmdGetMapTerrain(p)")
        return gamescript[start:start + 2600]

    def test_it_caps_the_tiles_returned(self, gamescript: str) -> None:
        body = self._handler(gamescript)
        assert "max_tiles" in body
        assert "if (max_tiles > 20000) max_tiles = 20000;" in body

    def test_it_says_when_it_cut_the_band_short(self, gamescript: str) -> None:
        """A short answer that looks complete is the failure this replaced. The caller
        is told it was truncated and where to resume."""
        body = self._handler(gamescript)
        assert "truncated" in body
        assert "next_from_y" in body
