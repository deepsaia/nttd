"""Pins the action vocabulary to human parity.

The rule: an agent may take any action a human player can take through the OpenTTD
GUI, and nothing more. Two failure directions matter, so both are tested.

  Superhuman powers leaking into play makes a score indefensible: an agent that
  can mint subsidies or grant itself money is not solving the same problem.

  Parity gaps make the benchmark measure the wrong thing: terraforming and
  conditional orders are what separates expert play from novice play, and all
  twelve were implemented in the GameScript but unreachable.

A drift test cross-checks the vocabulary against the GameScript dispatch table, so
a command cannot be added to one and forgotten in the other.

Run with: uv run pytest tests/test_action_vocabulary.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

from nttd.constants import (
    ACTION_CATEGORIES,
    KNOWN_ACTIONS,
    OPERATOR_ACTION_CATEGORIES,
    OPERATOR_ACTIONS,
)

_GAMESCRIPT = Path(__file__).resolve().parents[1] / "ottd_config" / "game" / "nttd-gs" / "main.nut"

# Read-only commands have their own observation surface, so they are not expected
# in the action vocabulary.
_READ_ONLY_PREFIXES = ("get_", "find_", "scan_", "ping")


def _gamescript_commands() -> set[str]:
    """Top-level dispatch cases: `case "x": return this.CmdY(p);`.

    Deliberately narrow: matching every `case "..."` also picks up vehicle-type
    parsing helpers like `case "train"`, which are not commands.
    """
    return set(re.findall(r'case "([a-z_0-9]+)":\s*return this\.Cmd', _GAMESCRIPT.read_text()))


# ---------------------------------------------------------------------------
# Superhuman powers must not be available for play
# ---------------------------------------------------------------------------


def test_no_action_is_both_play_and_authoring() -> None:
    assert not (KNOWN_ACTIONS & OPERATOR_ACTIONS)


def test_subsidy_minting_is_operator_only() -> None:
    """A human can only claim a subsidy the game offers."""
    assert "create_subsidy" in OPERATOR_ACTIONS
    assert "create_subsidy" not in KNOWN_ACTIONS


def test_self_granted_money_and_credit_are_operator_only() -> None:
    for action in ("change_bank_balance", "set_max_loan"):
        assert action in OPERATOR_ACTIONS, action
        assert action not in KNOWN_ACTIONS, action


def test_world_shaping_deity_powers_are_operator_only() -> None:
    for action in (
        "found_town", "expand_town", "set_town_growth",
        "change_town_rating", "set_cargo_goal", "set_game_setting",
    ):
        assert action in OPERATOR_ACTIONS, action
        assert action not in KNOWN_ACTIONS, action


# ---------------------------------------------------------------------------
# Real GUI mechanics must stay available
# ---------------------------------------------------------------------------


def test_town_actions_remain_available() -> None:
    """perform_town_action covers advertising, funding, statues, road works,
    bribing the local authority, and buying exclusive transport rights.

    All are buttons in the town window, so a human can use every one. Bribery and
    exclusive rights are aggressive but legitimate strategy, not a special power.
    """
    assert "perform_town_action" in KNOWN_ACTIONS


def test_cost_estimation_is_available() -> None:
    """A human sees the price in the build cursor before committing.

    Withholding it was a parity gap, not a safeguard.
    """
    assert "estimate_cost" in KNOWN_ACTIONS


def test_terraforming_is_available() -> None:
    for action in ("raise_tile", "lower_tile", "level_tiles"):
        assert action in KNOWN_ACTIONS, action


def test_conditional_orders_are_available() -> None:
    """Without these an agent cannot express "skip unless load < 50%" at all."""
    for action in (
        "set_order_condition", "set_order_compare_function",
        "set_order_compare_value", "set_stop_location",
    ):
        assert action in KNOWN_ACTIONS, action


def test_one_way_roads_and_conversion_are_available() -> None:
    for action in ("build_one_way_road", "build_one_way_road_full", "convert_road_type"):
        assert action in KNOWN_ACTIONS, action


def test_tree_planting_is_available() -> None:
    """How a human repairs a town's opinion of them."""
    for action in ("plant_tree", "plant_tree_rectangle"):
        assert action in KNOWN_ACTIONS, action


# ---------------------------------------------------------------------------
# Drift between the vocabulary and the GameScript
# ---------------------------------------------------------------------------


def test_every_declared_action_exists_in_the_gamescript() -> None:
    """A declared action with no handler fails at runtime with a confusing error."""
    declared = KNOWN_ACTIONS | OPERATOR_ACTIONS
    missing = sorted(declared - _gamescript_commands())
    assert not missing, f"declared but not dispatched by the GameScript: {missing}"


def test_no_mutating_gamescript_command_is_unreachable() -> None:
    """Every implemented mutating command must be assigned to a tier.

    An unassigned one is a capability nobody can use and nobody decided to
    withhold, which is how the twelve parity gaps went unnoticed.
    """
    unassigned = _gamescript_commands() - KNOWN_ACTIONS - OPERATOR_ACTIONS
    mutating = sorted(
        c for c in unassigned if not c.startswith(_READ_ONLY_PREFIXES)
    )
    assert not mutating, f"mutating commands assigned to no tier: {mutating}"


def test_categories_have_no_duplicates() -> None:
    for name, actions in {**ACTION_CATEGORIES, **OPERATOR_ACTION_CATEGORIES}.items():
        assert len(actions) == len(set(actions)), f"duplicates in {name}"


def test_flat_sets_match_their_categories() -> None:
    assert KNOWN_ACTIONS == {a for group in ACTION_CATEGORIES.values() for a in group}
    assert OPERATOR_ACTIONS == {
        a for group in OPERATOR_ACTION_CATEGORIES.values() for a in group
    }


# ---------------------------------------------------------------------------
# Parameter validation for the newly reachable actions
# ---------------------------------------------------------------------------


def test_newly_exposed_actions_have_parameter_validation() -> None:
    """Exposing an action without validation just moves the error later.

    Catching a missing parameter locally costs nothing; letting it through spends
    a round trip to the game to learn the same thing.
    """
    from nttd.interpreter.validator import _REQUIRED_PARAMS

    for action in (
        "raise_tile", "lower_tile", "level_tiles",
        "plant_tree", "plant_tree_rectangle",
        "build_one_way_road", "build_one_way_road_full", "convert_road_type",
        "set_order_condition", "set_order_compare_function",
        "set_order_compare_value", "set_stop_location",
        "estimate_cost",
    ):
        assert action in _REQUIRED_PARAMS, f"{action} has no parameter validation"


def test_declared_params_match_the_gamescript_handlers() -> None:
    """Guards against the validator drifting from the handler it mirrors.

    Verified live: the names below are what the GameScript actually requires, and
    raise_tile, level_tiles, and build_one_way_road succeed against a real game
    when given exactly these.
    """
    from nttd.interpreter.validator import _REQUIRED_PARAMS

    expected = {
        "raise_tile": ["x", "y", "slope"],
        "level_tiles": ["x1", "y1", "x2", "y2"],
        "build_one_way_road": ["x1", "y1", "x2", "y2"],
        "set_stop_location": ["vehicle_id", "order_pos", "stop_location"],
    }
    for action, params in expected.items():
        assert _REQUIRED_PARAMS[action] == params, action


def test_missing_params_are_reported_with_the_action_name() -> None:
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([AgentAction(action_type="raise_tile", parameters={"x": 1})])
    assert 0 in errors
    assert "raise_tile" in errors[0]
    assert "y" in errors[0] and "slope" in errors[0]


def test_wrong_param_shape_gets_a_hint() -> None:
    """A single x,y is the natural guess for an area operation."""
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([
        AgentAction(action_type="level_tiles", parameters={"x": 1, "y": 2, "width": 3, "height": 4}),
    ])
    assert "corner pair" in errors[0]


def test_operator_action_is_rejected_before_param_checks() -> None:
    """The tier refusal must be the reason given, not a parameter complaint."""
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([AgentAction(action_type="create_subsidy", parameters={})])
    assert "operator-tier" in errors[0]
