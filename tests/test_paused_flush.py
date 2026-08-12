"""Which batches have to run against a moving world, and which do not.

A step used to unpause for every batch. That made an ordinary batch of builds spend real
game-days executing, and, in the words of the step's own comment, let a slow batch outrun
its own interval. Only two of the 77 participant actions actually need the game running,
so the rest can now execute against a still world and cost exactly nothing.

The set is derived from the GameScript dispatch table rather than maintained by hand, so
the test that matters most here is the one that checks it against main.nut.
"""

from __future__ import annotations

import re
from pathlib import Path

from nttd.constants import KNOWN_ACTIONS, TICK_DEPENDENT_ACTIONS
from nttd.runtime.orchestrator import _needs_game_ticks

GAMESCRIPT = Path(__file__).resolve().parents[1] / "ottd_config/game/nttd-gs/main.nut"


def _yielding_handlers() -> set[str]:
    """Handlers whose body reaches a yield, which is what needs game ticks."""
    lines = GAMESCRIPT.read_text().split("\n")
    current = ""
    yielding: set[str] = set()
    for line in lines:
        declared = re.match(r"\s*function\s+(\w+)\s*\(", line)
        if declared:
            current = declared.group(1)
        if "_YieldAndProcessEvents" in line and "function" not in line:
            yielding.add(current)
    return yielding


def _dispatched_names(handlers: set[str]) -> set[str]:
    """The action names that reach any of those handlers, directly or through a caller."""
    source = GAMESCRIPT.read_text()
    lines = source.split("\n")
    current = ""
    callers: set[str] = set()
    for line in lines:
        declared = re.match(r"\s*function\s+(\w+)\s*\(", line)
        if declared:
            current = declared.group(1)
        for handler in handlers:
            if f"{handler}(" in line and "function" not in line:
                callers.add(current)
    names: set[str] = set()
    for caller in callers:
        for found in re.finditer(
            r'case\s+"([a-z_0-9]+)":\s*return\s+this\.' + caller + r"\b", source,
        ):
            names.add(found.group(1))
    return names


# ----------------------------------------------------------------------


def test_the_set_matches_what_the_gamescript_actually_yields_in() -> None:
    """The one test worth having: the list cannot drift from the game.

    If a new handler starts yielding, or connect_rail stops, this fails rather than
    letting a step silently deadlock or silently waste game-days.
    """
    assert _dispatched_names(_yielding_handlers()) == set(TICK_DEPENDENT_ACTIONS)


def test_only_two_actions_out_of_the_whole_surface_need_ticks() -> None:
    assert TICK_DEPENDENT_ACTIONS == {"connect_rail", "connect_road"}
    assert len(KNOWN_ACTIONS) > 70
    assert TICK_DEPENDENT_ACTIONS <= KNOWN_ACTIONS


def test_an_empty_batch_needs_nothing() -> None:
    assert _needs_game_ticks([]) is False
    assert _needs_game_ticks(None) is False


def test_a_batch_of_ordinary_builds_runs_against_a_still_world() -> None:
    batch = [
        {"action": "build_rail_station", "params": {"tile": 1}},
        {"action": "build_rail_depot", "params": {"tile": 2}},
        {"action": "buy_vehicle", "params": {"engine_id": 12}},
    ]
    assert _needs_game_ticks(batch) is False


def test_one_pathfinding_action_anywhere_in_the_batch_is_enough() -> None:
    """Length decides whether a search reaches its yield, and that is not knowable
    beforehand, so the whole batch runs with the world moving."""
    batch = [
        {"action": "build_rail_station", "params": {}},
        {"action": "connect_rail", "params": {}},
        {"action": "buy_vehicle", "params": {}},
    ]
    assert _needs_game_ticks(batch) is True


def test_connect_road_counts_too() -> None:
    assert _needs_game_ticks([{"action": "connect_road", "params": {}}]) is True


def test_both_spellings_of_the_action_key_are_understood() -> None:
    """Batches arrive as action, and recorded envelopes carry action_type."""
    assert _needs_game_ticks([{"action_type": "connect_rail"}]) is True
    assert _needs_game_ticks([{"action_type": "build_rail_depot"}]) is False


def test_an_entry_with_no_action_name_does_not_raise() -> None:
    """A malformed batch is refused later by the gate; it must not break the decision."""
    assert _needs_game_ticks([{"params": {}}]) is False
    assert _needs_game_ticks([{"action": None}]) is False
