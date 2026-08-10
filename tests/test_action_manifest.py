"""The generated description of nttd's action surface.

nttd had no declarative account of what it can do. ``constants.py`` holds 129 names in
categories and nothing else, and ``ActionEnvelope.parameters`` is ``dict[str, Any]`` --
an opaque passthrough that forwards whatever it is handed to the GameScript. The only
place with the real contract is ``main.nut``, in Squirrel.

So the manifest is generated from there. The alternative, a hand-written copy, is the
defect this replaces: ``interpreter/validator.py`` covered 14 of 129 actions and had
already drifted, declaring ``plant_tree_rectangle`` takes ``x1,y1,x2,y2`` when the
GameScript reads ``x, y, width, height`` and refuses anything else, so a contestant
following nttd's own validator was rejected by the game.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).parent.parent
_MANIFEST = _ROOT / "config" / "actions" / "manifest.json"
_GENERATOR = _ROOT / "scripts" / "generate_action_manifest.py"


def _load_generator() -> ModuleType:
    """Import the generator, which lives in scripts/ rather than on the path."""
    spec = importlib.util.spec_from_file_location("_generate_action_manifest", _GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads(_MANIFEST.read_text())


@pytest.fixture(scope="module")
def actions(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["actions"]


class TestItCoversTheWholeSurface:
    def test_every_declared_action_is_present(self, actions: dict[str, Any]) -> None:
        """A missing action is one an agent cannot discover."""
        from nttd.constants import (
            KNOWN_ACTIONS,
            OPERATOR_ACTIONS,
            READ_ONLY_GS_ACTIONS,
        )

        declared = KNOWN_ACTIONS | OPERATOR_ACTIONS | READ_ONLY_GS_ACTIONS
        assert declared - set(actions) == set()

    def test_it_invents_nothing(self, actions: dict[str, Any]) -> None:
        """An action in the manifest that the GameScript cannot run is worse than a
        missing one: an agent would call it and get a refusal it cannot interpret."""
        from nttd.constants import (
            KNOWN_ACTIONS,
            OPERATOR_ACTIONS,
            READ_ONLY_GS_ACTIONS,
        )

        declared = KNOWN_ACTIONS | OPERATOR_ACTIONS | READ_ONLY_GS_ACTIONS
        assert set(actions) - declared == set()

    def test_every_action_has_a_tier(self, actions: dict[str, Any]) -> None:
        """A consumer must be able to tell a participant action from an operator one
        without a second lookup."""
        tiers = {entry["tier"] for entry in actions.values()}
        assert tiers <= {"participant", "operator", "read_only"}
        assert "unknown" not in tiers


class TestItMatchesTheGameScript:
    def test_the_parameters_come_from_the_implementation(
        self, actions: dict[str, Any],
    ) -> None:
        """Spot-checked against main.nut. These are the shapes a hand-written list
        gets wrong: a tile-or-coordinates pair, and optional values with defaults."""
        bridge = actions["build_bridge"]["parameters"]
        assert bridge["start_x"]["required"] is True
        assert bridge["end_y"]["required"] is True
        assert bridge["bridge_type"]["required"] is False

        stop = actions["build_road_stop"]["parameters"]
        for name in ("tile", "x", "y"):
            assert stop[name]["via"] == "tile_resolver", (
                "build_road_stop resolves a tile or an x,y pair through a helper, so "
                "the parameters never appear in its body"
            )

    def test_plant_tree_rectangle_matches_the_gamescript_not_the_old_list(
        self, actions: dict[str, Any],
    ) -> None:
        """The drift that motivated generating this.

        CmdPlantTreeRectangle requires x, y, width and height and refuses anything
        else, while interpreter/validator.py declared x1, y1, x2, y2.
        """
        params = set(actions["plant_tree_rectangle"]["parameters"])
        assert params == {"x", "y", "width", "height"}
        assert not params & {"x1", "y1", "x2", "y2"}

    def test_it_agrees_with_the_hand_written_list_everywhere_else(
        self, actions: dict[str, Any],
    ) -> None:
        """13 of the 14 hand-written entries were right, which is independent
        confirmation that the extraction is not inventing a plausible contract.

        Frozen as a literal because the table it came from is deleted. Reading it from
        the manifest would be the manifest agreeing with itself.
        """
        hand_written = {
            "build_bridge": ["start_x", "start_y", "end_x", "end_y"],
            "raise_tile": ["x", "y", "slope"],
            "lower_tile": ["x", "y", "slope"],
            "level_tiles": ["x1", "y1", "x2", "y2"],
            "plant_tree": ["x", "y"],
            "build_one_way_road": ["x1", "y1", "x2", "y2"],
            "build_one_way_road_full": ["x1", "y1", "x2", "y2"],
            "convert_road_type": ["x1", "y1", "x2", "y2"],
            "set_order_condition": ["vehicle_id", "order_pos", "condition"],
            "set_order_compare_function": ["vehicle_id", "order_pos", "compare_function"],
            "set_order_compare_value": ["vehicle_id", "order_pos", "value"],
            "set_stop_location": ["vehicle_id", "order_pos", "stop_location"],
            "estimate_cost": ["action", "params"],
            # plant_tree_rectangle is deliberately absent: its hand-written entry was
            # wrong, and the test above pins the GameScript's real shape instead.
        }
        for action, required in hand_written.items():
            present = set(actions[action]["parameters"])
            assert set(required) <= present, f"{action} lost {set(required) - present}"

    def test_company_id_is_never_a_parameter(self, actions: dict[str, Any]) -> None:
        """nttd derives it from the participant token and overwrites whatever the
        caller sent, so offering it to an agent would invite a pointless mistake."""
        for name, entry in actions.items():
            assert "company_id" not in entry["parameters"], name

    def test_actions_reading_only_company_id_take_no_parameters(
        self, actions: dict[str, Any],
    ) -> None:
        """get_stations and friends take `p` but read nothing from it but the company,
        so an empty parameter list is correct rather than a failed extraction."""
        for name in ("get_stations", "get_company_finance", "get_groups"):
            assert actions[name]["parameters"] == {}


class TestEverythingIsDescribed:
    def test_every_action_has_prose(self, actions: dict[str, Any]) -> None:
        """An undescribed action is one an agent can name but cannot use."""
        missing = sorted(name for name, entry in actions.items() if not entry["description"])
        assert missing == []

    def test_every_parameter_has_prose_and_a_type(self, actions: dict[str, Any]) -> None:
        missing = sorted(
            f"{name}.{param}"
            for name, entry in actions.items()
            for param, meta in entry["parameters"].items()
            if not meta.get("description") or not meta.get("type")
        )
        assert missing == []

    def test_a_repeated_parameter_says_the_same_thing(self, actions: dict[str, Any]) -> None:
        """`x` appears in 36 actions. Describing it 36 times invites 36 slightly
        different descriptions, so the glossary supplies one and an action overrides it
        only where the meaning genuinely differs."""
        seen: dict[str, set[str]] = {}
        for entry in actions.values():
            for param, meta in entry["parameters"].items():
                seen.setdefault(param, set()).add(meta["description"])

        overridden = {"direction", "transport_type", "action", "vehicle_type"}
        inconsistent = {
            param: descriptions
            for param, descriptions in seen.items()
            if len(descriptions) > 1 and param not in overridden
        }
        assert inconsistent == {}


class TestEnumValuesComeFromTheBuild:
    """The values are read from OpenTTD by scripts/dump_gs_enums.py rather than typed.

    A wrong constant is worse than a missing one: it is a plausible value the game
    accepts and acts on, and several of these collide. OF_UNLOAD and
    OF_SERVICE_IF_NEEDED are both 4; OF_TRANSFER and OF_STOP_IN_DEPOT are both 8.
    """

    def test_the_manifest_matches_the_dump_exactly(self, actions: dict[str, Any]) -> None:
        dumped = json.loads((_ROOT / "config" / "actions" / "enums.json").read_text())["enums"]
        for name, entry in actions.items():
            for param, meta in entry["parameters"].items():
                if "enum" not in meta:
                    continue
                source = dumped[meta["enum"]["class"]]
                for constant, value in meta["enum"]["values"].items():
                    assert source[constant] == value, f"{name}.{param}.{constant}"

    def test_the_values_are_the_ones_openttd_reported(self, actions: dict[str, Any]) -> None:
        """Spot checks that would each be an easy thing to get wrong by hand."""
        flags = actions["add_order"]["parameters"]["order_flags"]["enum"]["values"]
        assert flags["OF_FULL_LOAD"] == 64
        assert flags["OF_NO_LOAD"] == 128
        assert flags["OF_UNLOAD"] == flags["OF_SERVICE_IF_NEEDED"] == 4

        track = actions["remove_rail_track"]["parameters"]["track"]["enum"]["values"]
        assert track["RAILTRACK_NE_SW"] == 1
        assert track["RAILTRACK_NW_SE"] == 2

    def test_invalid_sentinels_are_not_offered(self, actions: dict[str, Any]) -> None:
        """Every one of these enums carries an _INVALID member. It is a return value
        meaning "none", not something to pass in."""
        for entry in actions.values():
            for meta in entry["parameters"].values():
                offered = list(meta.get("enum", {}).get("values", {}))
                assert not [name for name in offered if name.endswith("_INVALID")]


class TestAlternatives:
    """Actions that accept a choice of parameters.

    The first manifest marked every mentioned parameter required, which is wrong
    wherever the GameScript accepts alternatives: insert_order came out demanding
    station_id and dest_tile and destination at once, which no caller can satisfy.
    """

    def test_no_single_alternative_is_required(self, actions: dict[str, Any]) -> None:
        params = actions["insert_order"]["parameters"]
        for name in ("station_id", "dest_tile", "destination"):
            assert params[name]["required"] is False
        assert params["vehicle_id"]["required"] is True

    def test_the_choice_is_published(self, actions: dict[str, Any]) -> None:
        groups = actions["insert_order"]["one_of"]
        assert ["station_id"] in groups[0]
        assert ["dest_tile"] in groups[0]

    def test_a_branch_can_be_more_than_one_parameter(self, actions: dict[str, Any]) -> None:
        """build_train takes depot_tile, or depot_x and depot_y as a pair. Treating each
        branch as a single name left depot_y required, which nobody passing depot_tile
        could satisfy."""
        entry = actions["build_train"]
        assert entry["parameters"]["depot_y"]["required"] is False
        assert ["depot_x", "depot_y"] in entry["one_of"][0]

    def test_tile_or_coordinates_is_derived_not_declared(self, actions: dict[str, Any]) -> None:
        """Every action resolving a tile through the shared helper needs tile or x,y.
        That comes from the helper rather than being declared 11 times."""
        for name in ("build_road_stop", "remove_rail_track", "find_flat_spots"):
            assert [["tile"], ["x", "y"]] in actions[name]["one_of"], name


def _handler_bodies() -> dict[str, str]:
    """Each dispatched action's handler body, found without the generator's help.

    Deliberately a second implementation. Reusing the generator's own parsing would make
    the drift test the generator agreeing with itself, which is the failure mode this
    whole file exists to avoid.
    """
    source = (_ROOT / "ottd_config" / "game" / "nttd-gs" / "main.nut").read_text()
    dispatch = dict(re.findall(r'case\s+"([a-z_0-9]+)":\s*return\s+this\.(Cmd\w+)\(', source))

    bodies: dict[str, str] = {}
    for action, function in dispatch.items():
        start = source.find(f"function {function}(")
        if start < 0:
            continue
        opening = source.index("{", start)
        depth, index = 1, opening + 1
        while index < len(source) and depth:
            depth += {"{": 1, "}": -1}.get(source[index], 0)
            index += 1
        bodies[action] = source[opening:index]
    return bodies


def _parameters_the_handler_reads(body: str) -> set[str]:
    """Every parameter name the body touches, by a simpler route than the generator."""
    read = set(re.findall(r"\bp\.([a-z_0-9]+)", body))
    tested = set(re.findall(r'"([a-z_0-9]+)"\s+in\s+p\b', body))
    return (read | tested) - {"company_id"}


class TestTheManifestAndTheGameScriptAgreeBothWays:
    """Neither side may hold a parameter the other does not.

    The reproducibility test covers one direction and only by construction: regenerate,
    and of course the output matches the input it was made from. It says nothing about
    whether the extraction is reading the handler correctly, and nothing at all about
    hand-written prose that has stopped matching anything.
    """

    def test_no_parameter_the_handler_reads_is_missing(self, actions: dict[str, Any]) -> None:
        """A dropped parameter is invisible: the action still works for anyone who knows
        to pass it, and is undiscoverable for everyone else."""
        missing: list[str] = []
        for action, body in _handler_bodies().items():
            published = set(actions[action]["parameters"])
            for param in _parameters_the_handler_reads(body) - published:
                missing.append(f"{action}.{param}")
        assert sorted(missing) == []

    def test_no_published_parameter_is_absent_from_the_handler(
        self, actions: dict[str, Any],
    ) -> None:
        """The opposite rot: a parameter offered to agents that the game ignores.

        Parameters supplied by a shared tile helper are exempt, because the helper reads
        them and the handler never names them.
        """
        from_helper = {"tile", "x", "y", "tile_from", "tile_to",
                       "from_x", "from_y", "to_x", "to_y"}
        invented: list[str] = []
        for action, body in _handler_bodies().items():
            read = _parameters_the_handler_reads(body)
            for param in set(actions[action]["parameters"]) - read - from_helper:
                invented.append(f"{action}.{param}")
        assert sorted(invented) == []


class TestTheExamplesInTheSourceAreReal:
    """Every ``{"action_type": ..., "parameters": {...}}`` shown to an agent.

    These are the most quietly wrong thing in the repo, because an agent copies the
    format it is shown rather than looking the action up. The example in
    ``action_schema.py`` passed ``length`` to ``build_road_stop``, which takes
    ``direction``, ``is_drive_through``, ``is_truck_stop``, ``road_type`` and a tile, and
    nothing named ``length`` at all. It was repeated in the MCP server's system prompt.
    """

    def _examples(self) -> list[tuple[Path, str, dict[str, Any]]]:
        pattern = re.compile(
            r'\{\\?"action_type\\?":\s*\\?"([a-z_0-9]+)\\?",\s*\\?"parameters\\?":\s*(\{[^{}]*\})'
        )
        found: list[tuple[Path, str, dict[str, Any]]] = []
        for path in sorted((_ROOT / "src").rglob("*.py")):
            for action, params in pattern.findall(path.read_text()):
                cleaned = params.replace('\\"', '"')
                try:
                    parsed = json.loads(cleaned)
                except json.JSONDecodeError:
                    continue
                found.append((path, action, parsed))
        return found

    def test_there_are_examples_to_check(self) -> None:
        """A pattern that silently matches nothing would pass every assertion below."""
        assert len(self._examples()) >= 4

    def test_every_example_names_a_real_action(self) -> None:
        from nttd.config import action_manifest

        wrong = [
            f"{path.name}: {action}"
            for path, action, _ in self._examples()
            if action not in action_manifest.ACTIONS
        ]
        assert wrong == []

    def test_every_example_parameter_is_one_the_action_takes(self) -> None:
        from nttd.config import action_manifest

        wrong = [
            f"{path.name}: {action} has no parameter '{param}'"
            for path, action, params in self._examples()
            for param in params
            if param not in action_manifest.parameters(action)
        ]
        assert wrong == []

    def test_every_example_would_pass_validation(self) -> None:
        """Naming real parameters is not enough: the example must also satisfy whatever
        choice the action offers, or it is a shape that gets refused."""
        from nttd.interpreter.action_schema import AgentAction
        from nttd.interpreter.validator import validate_actions

        for path, action, params in self._examples():
            errors = validate_actions([AgentAction(action_type=action, parameters=params)])
            assert errors == {}, f"{path.name}: {errors}"


class TestStaleProseIsReported:
    """The direction regenerating cannot see.

    The generator merges prose by key and ignores keys matching nothing, which is what
    makes regenerating safe to run. It also means a description for a deleted action, or
    an enum binding whose class moved, rots silently: the parameter loses its values and
    nothing says so.
    """

    def _problems(self, written: dict[str, Any]) -> list[str]:
        generator = _load_generator()
        manifest = json.loads(_MANIFEST.read_text())
        return generator.problems(manifest, written)

    def test_the_committed_prose_is_clean(self) -> None:
        generator = _load_generator()
        assert self._problems(generator._descriptions()) == []

    def test_a_description_for_a_vanished_action_is_caught(self) -> None:
        found = self._problems({"actions": {"build_monorail_to_the_moon": {"description": "x"}}})
        assert any("build_monorail_to_the_moon" in problem for problem in found)

    def test_an_override_for_a_parameter_the_action_lacks_is_caught(self) -> None:
        found = self._problems({
            "actions": {"build_dock": {"parameters": {"altitude": {"description": "x"}}}},
        })
        assert any("build_dock.altitude" in problem for problem in found)

    def test_a_glossary_entry_nobody_uses_is_caught(self) -> None:
        found = self._problems({"parameter_glossary": {"velocity": {"type": "integer"}}})
        assert any("velocity" in problem for problem in found)

    def test_a_binding_matching_no_parameter_is_caught(self) -> None:
        found = self._problems({
            "enum_bindings": {"build_dock.mooring": {"class": "GSMarine", "prefix": "MO_"}},
        })
        assert any("build_dock.mooring" in problem for problem in found)

    def test_a_binding_to_constants_openttd_does_not_have_is_caught(self) -> None:
        """The quiet one. The binding still names a real parameter, so nothing looks
        wrong, and the parameter simply loses every value it should have offered."""
        found = self._problems({
            "enum_bindings": {"set_order_condition.condition": {"class": "GSOrder", "prefix": "ZZ_"}},
        })
        assert any("ZZ_" in problem for problem in found)

    def test_an_alternative_naming_an_absent_parameter_is_caught(self) -> None:
        found = self._problems({
            "actions": {"build_dock": {"one_of": [["x", "harbour_id"]]}},
        })
        assert any("build_dock.harbour_id" in problem for problem in found)


class TestItIsReproducible:
    def test_regenerating_changes_nothing(self, manifest: dict[str, Any]) -> None:
        """A committed manifest that differs from its generator is a manifest nobody
        can trust to describe the GameScript.

        The reference pages are covered too. They are a third rendering of the same
        source, and a stale one reads exactly like a current one.
        """
        watched = [_MANIFEST, *sorted((_ROOT / "docs" / "actions").glob("*.md"))]
        before = {path: path.read_text() for path in watched}
        subprocess.run(
            [sys.executable, str(_GENERATOR)], cwd=_ROOT, check=True, capture_output=True,
        )
        for path in watched:
            assert path.read_text() == before[path], (
                f"{path.name} is stale: "
                "run uv run python scripts/generate_action_manifest.py"
            )

    def test_the_index_covers_everything_and_stays_small(
        self, actions: dict[str, Any],
    ) -> None:
        """Choosing an action should not cost reading every action.

        actions.md is about 9k tokens. The question "which action do I want" is answered
        by the index at roughly a third of that, for all 129 rather than one tier.
        """
        index = (_ROOT / "docs" / "actions" / "index.md").read_text()
        playable = [n for n, e in actions.items() if e["tier"] != "operator"]
        for name in playable:
            assert f"`{name}(" in index, f"{name} has no signature in the index"

        detail = (_ROOT / "docs" / "actions" / "actions.md").read_text()
        assert len(index) < len(detail), (
            "the index covers all three tiers and must still be smaller than one "
            "detail page, or it is not worth reading first"
        )

    def test_a_signature_shows_what_a_call_needs(self) -> None:
        """Required first, choices as a|b, optional in brackets. Without this an agent
        must open the section to learn whether it can call the thing at all."""
        index = (_ROOT / "docs" / "actions" / "index.md").read_text()
        assert "`remove_order(vehicle_id, order_index|order_position)`" in index
        assert "`build_train(engine_id, depot_tile|depot_x,depot_y," in index

    def test_the_reference_is_split_by_what_an_action_does(self) -> None:
        """The whole surface is about 16k tokens. An agent deciding what to observe
        should not have to read 76 build actions to do it."""
        reference = _ROOT / "docs" / "actions"
        observations = (reference / "observations.md").read_text()
        assert "get_stations" in observations
        assert "### `build_rail_station`" not in observations
        assert "### `build_rail_station`" in (reference / "actions.md").read_text()


class TestOperatorActionsAreNotDocumentedForPlayers:
    """Nobody playing a session can call one, so the pages a player reads do not carry
    their parameters. That cost about 1100 tokens to tell a reader about actions they
    cannot use.

    They are still named in the index page, because nttd's claim is that nine superhuman
    actions exist and are refused, and a claim nobody can check is worth less.
    """

    def _operators(self, actions: dict[str, Any]) -> list[str]:
        return sorted(n for n, e in actions.items() if e["tier"] == "operator")

    def test_they_have_no_page_of_their_own(self) -> None:
        assert not (_ROOT / "docs" / "actions" / "operator.md").exists()

    def test_they_are_absent_from_the_pages_a_player_reads(
        self, actions: dict[str, Any],
    ) -> None:
        pages = ["index.md", "observations.md", "actions.md"]
        for filename in pages:
            text = (_ROOT / "docs" / "actions" / filename).read_text()
            for name in self._operators(actions):
                assert f"`{name}(" not in text, f"{name} is documented in {filename}"

    def test_the_reference_still_names_every_one(self, actions: dict[str, Any]) -> None:
        """Removing the page should not make them undiscoverable. A benchmark that
        quietly holds powers it does not mention is harder to trust than one that lists
        them and says they are refused."""
        text = (_ROOT / "docs" / "action_reference.md").read_text()
        for name in self._operators(actions):
            assert f"`{name}`" in text

    def test_they_keep_their_full_entry_in_the_manifest(
        self, actions: dict[str, Any],
    ) -> None:
        """The admin routes that can call them look them up here."""
        entry = actions["found_town"]
        assert entry["parameters"]["x"]["description"]
        assert entry["parameters"]["size"]["enum"]["values"]["TOWN_SIZE_SMALL"] == 0

    def test_the_cli_still_prints_them(self, capsys: pytest.CaptureFixture[str]) -> None:
        """An operator setting up a scenario needs somewhere to look."""
        from nttd.cli.actions_command import actions as actions_command

        actions_command(operator=True)
        output = capsys.readouterr().out
        assert "found_town" in output
        assert "build_rail_station" not in output

    def test_it_records_where_it_came_from(self, manifest: dict[str, Any]) -> None:
        assert manifest["generated_from"].endswith("main.nut")


# ---------------------------------------------------------------------------
# `nttd actions`
# ---------------------------------------------------------------------------


class TestTheActionsCommand:
    def test_an_action_with_only_optional_parameters_still_shows_them(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A display bug, not an extraction one, and it read as the opposite.

        The optional list was wrapped in square brackets, which rich parses as markup:
        it read "[tile," as a style tag and swallowed the rest, so remove_rail_track
        rendered as taking no parameters when the manifest holds four.
        """
        from nttd.cli.actions_command import actions as actions_command

        actions_command(category="rail")
        output = capsys.readouterr().out
        assert "remove_rail_track" in output
        for name in ("tile", "track"):
            assert name in output, f"{name} was swallowed before reaching the terminal"

    def test_one_action_shows_its_parameters(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from nttd.cli.actions_command import actions as actions_command

        actions_command(action="build_bridge")
        output = capsys.readouterr().out
        for name in ("start_x", "end_y", "bridge_type"):
            assert name in output

    def test_an_unknown_action_exits_rather_than_printing_nothing(self) -> None:
        import typer

        from nttd.cli.actions_command import actions as actions_command

        with pytest.raises(typer.Exit):
            actions_command(action="no_such_action")

    def test_playable_excludes_operator_actions(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A contestant reading the list should not see powers they cannot use."""
        from nttd.cli.actions_command import actions as actions_command

        actions_command(playable=True)
        output = capsys.readouterr().out
        assert "change_bank_balance" not in output
        assert "build_road_stop" in output

    def test_it_reports_no_gaps_now_that_there_are_none(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """This asserted the opposite while the manifest was a skeleton. Keeping it
        pointed the other way is what makes the gap notice meaningful: it should appear
        when something really is undescribed, not as permanent decoration."""
        from nttd.cli.actions_command import actions as actions_command

        actions_command(category="rail")
        output = capsys.readouterr().out
        assert "no description yet" not in output.lower()

    def test_observations_and_actions_are_listed_apart(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Reading the world and changing it are used differently, and grouping by
        category alone put get_stations next to build_rail_station."""
        from nttd.cli.actions_command import actions as actions_command

        actions_command(observations=True)
        output = capsys.readouterr().out
        assert "Observations" in output
        assert "get_stations" in output
        assert "build_rail_station" not in output

    def test_it_prints_the_constants_a_parameter_accepts(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Without these an agent has the parameter name and no way to choose a value:
        `condition` is an integer, and which integer is the whole question."""
        from nttd.cli.actions_command import actions as actions_command

        actions_command(action="set_order_condition")
        output = capsys.readouterr().out
        assert "OC_UNCONDITIONALLY" in output
        assert "OC_LOAD_PERCENTAGE = 0" in output

    def test_it_prints_the_alternatives(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from nttd.cli.actions_command import actions as actions_command

        actions_command(action="add_order")
        output = capsys.readouterr().out
        assert "Supply one of" in output
        assert "station_id" in output


class TestHandlersTheDispatchTableNeverReaches:
    """The blind spot the other checks structurally cannot see.

    Everything else here compares the manifest against the GameScript, and the manifest
    is *derived from* the dispatch table. A handler with no ``case`` is therefore not a
    mismatch anywhere: it is absent from the manifest, the docs and every parity test,
    which all agree with each other about a function nobody can call.

    Four accumulated that way. Three were build_path with a shorter list; the fourth was
    ``build_rail_track``, the missing inverse of ``remove_rail_track``, so the surface
    had a remove with no build for as long as nobody read the Squirrel.
    """

    def test_the_gamescript_has_no_unreachable_handlers(self) -> None:
        generator = _load_generator()
        assert generator._orphan_problems() == []

    def test_an_unreachable_handler_is_caught(self, tmp_path: Path) -> None:
        """Proved by removing a real dispatch case rather than by inspection: a check
        that has never fired is a check nobody knows the shape of."""
        generator = _load_generator()
        original = generator.GAMESCRIPT.read_text()
        case = 'case "build_rail_track":    return this.CmdBuildRailTrack(p);'
        assert case in original, "the case this test removes has been reworded"

        stand_in = tmp_path / "main.nut"
        stand_in.write_text(original.replace(case, ""))
        generator.GAMESCRIPT = stand_in

        found = generator._orphan_problems()
        assert any("CmdBuildRailTrack" in problem for problem in found)
        assert generator.GAMESCRIPT.read_text() != original

    def test_build_rail_track_is_reachable_and_described(
        self, actions: dict[str, Any],
    ) -> None:
        """The one orphan that was kept, because a path implies its orientations from
        the tiles either side and a siding has no path to imply anything."""
        entry = actions["build_rail_track"]
        assert entry["gamescript_function"] == "CmdBuildRailTrack"
        assert entry["tier"] == "participant"
        assert entry["category"] == "rail"
        assert entry["parameters"]["track"]["enum"]["values"]["RAILTRACK_NE_SW"] == 1

    @pytest.mark.parametrize("gone", ["build_road", "build_road_line", "build_rail"])
    def test_the_three_redundant_ones_are_gone(
        self, actions: dict[str, Any], gone: str,
    ) -> None:
        assert gone not in actions

    def test_build_path_tells_an_agent_it_can_lay_its_own_route(
        self, actions: dict[str, Any],
    ) -> None:
        """It could always do this. The description said it existed 'for a pathfinder
        that plans elsewhere', which reads as 'not for you' to somebody writing an agent,
        and that framing is why the redundant primitives looked like a missing feature."""
        description = actions["build_path"]["description"]
        assert "route you have already chosen" in description
        assert "nothing has to reason about track orientation" in description
