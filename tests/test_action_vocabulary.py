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
# A command that only reads. Prefixes rather than a list, because the point is to catch a
# NEW mutating command that nobody tiered, and a prefix rule keeps working as they arrive.
# trace_route is named for what it answers rather than for reading, so it is spelled out.
_READ_ONLY_PREFIXES = ("get_", "find_", "scan_", "ping", "trace_")


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

    Validation is either a required parameter or an alternation, and for a tile action
    it is now the second: the dispatcher resolves ``tile`` into ``x, y``, so neither
    axis is required on its own and "supply a tile, one way or the other" is expressed
    as ``one_of``. Asserting on required parameters alone would call that unvalidated
    when it is simply validated differently.
    """
    from nttd.config import action_manifest

    for action in (
        "raise_tile", "lower_tile", "level_tiles",
        "plant_tree", "plant_tree_rectangle",
        "build_one_way_road", "build_one_way_road_full", "convert_road_type",
        "set_order_condition", "set_order_compare_function",
        "set_order_compare_value", "set_stop_location",
        "estimate_cost",
    ):
        assert (
            action_manifest.required_parameters(action)
            or action_manifest.alternatives(action)
        ), f"{action} has neither a required parameter nor an alternation"


def test_declared_params_match_the_gamescript_handlers() -> None:
    """Independently authored expectations, frozen here.

    These names were verified live against a real game before the manifest existed:
    raise_tile, level_tiles and build_one_way_road each succeed when given exactly
    these. Keeping them as literals is what makes this a real check rather than the
    manifest agreeing with itself.

    Asserted through the validator rather than against `required_parameters`, because
    requiredness is no longer the whole story. The dispatcher resolves `tile` into
    `x, y`, so on a tile action neither axis is required alone and the obligation lives
    in `one_of` instead. Supplying exactly these names must still validate cleanly,
    which is the property that was really being checked and is a stronger claim than
    comparing one list.
    """
    from nttd.config import action_manifest
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    expected = {
        "raise_tile": ["slope", "x", "y"],
        "level_tiles": ["x1", "x2", "y1", "y2"],
        "build_one_way_road": ["x1", "x2", "y1", "y2"],
        "set_stop_location": ["order_pos", "stop_location", "vehicle_id"],
    }
    for action, params in expected.items():
        accepted = set(action_manifest.accepted_parameters(action))
        assert set(params) <= accepted, f"{action} no longer accepts {sorted(set(params) - accepted)}"

        supplied = AgentAction(action_type=action, parameters=dict.fromkeys(params, 1))
        assert not validate_actions([supplied]), f"{action} refused its own verified shape"


def test_missing_params_are_reported_with_the_action_name() -> None:
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([AgentAction(action_type="raise_tile", parameters={"x": 1})])
    assert 0 in errors
    assert "raise_tile" in errors[0]
    assert "y" in errors[0] and "slope" in errors[0]


def test_a_wrong_param_shape_is_told_the_real_one() -> None:
    """A single x,y is the natural guess for an area operation.

    The message names what the action actually accepts, generated from the manifest,
    rather than a hand-written hint. The hints this replaced had drifted with the
    table beside them: the one for plant_tree_rectangle advised the very parameter
    names the GameScript refuses.
    """
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([
        AgentAction(action_type="level_tiles", parameters={"x": 1, "y": 2, "width": 3, "height": 4}),
    ])
    for name in ("x1", "y1", "x2", "y2"):
        assert name in errors[0], "the message must name the shape the game wants"

    # And the reverse case the old hint got backwards: it advised x1,y1,x2,y2 for
    # plant_tree_rectangle, which is precisely what the GameScript refuses.
    errors = validate_actions([
        AgentAction(action_type="plant_tree_rectangle", parameters={"x1": 1, "y1": 2}),
    ])
    for name in ("x", "y", "width", "height"):
        assert name in errors[0]
    assert "x1" not in errors[0]


def test_an_action_offering_a_choice_accepts_any_branch() -> None:
    """The regression this guards is one the manifest itself caused.

    Marking every mentioned parameter required made insert_order demand station_id and
    dest_tile and destination at once, so a correct submission naming one destination
    was refused by nttd before the game ever saw it.
    """
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    for destination in ({"station_id": 3}, {"dest_tile": 4096}, {"destination": 4096}):
        errors = validate_actions([
            AgentAction(
                action_type="insert_order",
                parameters={"vehicle_id": 1, "order_index": 0, **destination},
            ),
        ])
        assert errors == {}, f"{destination} should satisfy the choice: {errors}"


def test_an_action_satisfying_no_branch_is_refused() -> None:
    """The other half: none of those parameters is required on its own, so checking
    requiredness alone would let through an order naming nowhere to go."""
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([
        AgentAction(action_type="insert_order", parameters={"vehicle_id": 1, "order_index": 0}),
    ])
    assert 0 in errors
    assert "one of" in errors[0]
    assert "station_id" in errors[0]


def test_a_paired_branch_needs_both_of_its_parameters() -> None:
    """build_train takes depot_tile, or depot_x and depot_y together. Half a pair is
    not a branch."""
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    assert validate_actions([
        AgentAction(action_type="build_train", parameters={"engine_id": 1, "depot_x": 5}),
    ])
    assert validate_actions([
        AgentAction(
            action_type="build_train",
            parameters={"engine_id": 1, "depot_x": 5, "depot_y": 6},
        ),
    ]) == {}


def test_a_tile_can_be_given_either_way() -> None:
    """Actions resolving a tile take an index or a coordinate pair, and refuse neither."""
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    assert validate_actions([
        AgentAction(action_type="remove_rail_track", parameters={"tile": 4096}),
    ]) == {}
    assert validate_actions([
        AgentAction(action_type="remove_rail_track", parameters={"x": 10, "y": 12}),
    ]) == {}
    assert validate_actions([
        AgentAction(action_type="remove_rail_track", parameters={"track": 1}),
    ])


def test_operator_action_is_rejected_before_param_checks() -> None:
    """The tier refusal must be the reason given, not a parameter complaint."""
    from nttd.interpreter.action_schema import AgentAction
    from nttd.interpreter.validator import validate_actions

    errors = validate_actions([AgentAction(action_type="create_subsidy", parameters={})])
    assert "operator-tier" in errors[0]


# ---------------------------------------------------------------------------
# The observation query endpoint must not be a route around the allowlist
# ---------------------------------------------------------------------------


def test_read_only_set_excludes_every_action() -> None:
    """POST /state/gs/query reaches the GameScript directly, so anything in this
    set is callable without the action allowlist or the scored lock.

    Verified before the fix: set_max_loan raised a scored company's credit ceiling
    from 300,000 to 9,000,000 through that endpoint while the guarded twin at
    /actions/gs/execute correctly returned 403.
    """
    from nttd.constants import READ_ONLY_GS_ACTIONS

    assert not (READ_ONLY_GS_ACTIONS & KNOWN_ACTIONS)
    assert not (READ_ONLY_GS_ACTIONS & OPERATOR_ACTIONS)


def test_read_only_set_contains_no_mutating_command() -> None:
    """Cross-check the hand-maintained set against the GameScript.

    A command whose handler writes must never be reachable as a "query", so this
    fails if a mutator is added to the set by mistake.
    """
    from nttd.constants import READ_ONLY_GS_ACTIONS

    mutating_prefixes = (
        "build_", "remove_", "connect_", "buy_", "sell_", "start_", "stop_",
        "create_", "delete_", "move_", "add_", "insert_", "skip_", "share_",
        "copy_", "set_", "change_", "found_", "expand_", "convert_", "demolish_",
        "plant_", "raise_", "lower_", "level_", "clone_", "refit_", "reverse_",
        "rename_", "send_", "open_close_",
    )
    offenders = sorted(
        c for c in READ_ONLY_GS_ACTIONS if c.startswith(mutating_prefixes)
    )
    assert not offenders, f"mutating commands in the read-only set: {offenders}"


def test_read_only_commands_all_exist_in_the_gamescript() -> None:
    from nttd.constants import READ_ONLY_GS_ACTIONS

    # ping answers inline rather than delegating to a Cmd* handler, so it is not
    # matched by _gamescript_commands. Verify it separately.
    assert 'case "ping"' in _GAMESCRIPT.read_text()

    missing = sorted(READ_ONLY_GS_ACTIONS - _gamescript_commands() - {"ping"})
    assert not missing, f"read-only commands not dispatched by the GameScript: {missing}"


def test_every_read_only_gamescript_command_is_reachable() -> None:
    """An observation command left out of the set becomes silently unavailable."""
    from nttd.constants import READ_ONLY_GS_ACTIONS

    unreachable = sorted(
        c for c in _gamescript_commands()
        if c.startswith(_READ_ONLY_PREFIXES) and c not in READ_ONLY_GS_ACTIONS
    )
    assert not unreachable, f"read-only commands not exposed for query: {unreachable}"
