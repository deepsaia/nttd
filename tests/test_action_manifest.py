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

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).parent.parent
_MANIFEST = _ROOT / "config" / "actions" / "manifest.json"
_GENERATOR = _ROOT / "scripts" / "generate_action_manifest.py"


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


class TestItIsReproducible:
    def test_regenerating_changes_nothing(self, manifest: dict[str, Any]) -> None:
        """A committed manifest that differs from its generator is a manifest nobody
        can trust to describe the GameScript."""
        before = _MANIFEST.read_text()
        subprocess.run(
            [sys.executable, str(_GENERATOR)], cwd=_ROOT, check=True, capture_output=True,
        )
        assert _MANIFEST.read_text() == before, (
            "run: uv run python scripts/generate_action_manifest.py"
        )

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

    def test_it_says_how_much_is_undescribed(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Silence would read as a complete manifest, and an agent composing actions
        from it would be working from names alone."""
        from nttd.cli.actions_command import actions as actions_command

        actions_command(category="rail")
        output = capsys.readouterr().out
        assert "no description yet" in output.lower()
