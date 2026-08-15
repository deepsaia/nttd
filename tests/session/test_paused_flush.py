"""Which GameScript actions search for a route, and so cannot finish without ticks.

A flush that ran while the game was paused was tried on 2026-08-12 and wedged the session:
every GameScript command issued during it timed out, and the admin stream then filled with
unparseable packets as the unanswered replies arrived late. The GameScript does not process
commands on a paused game at all, so the step still flushes with the world moving.

What survives is the knowledge of which actions search, because that is what issue #58 has
to replace with the Python planner. It is derived from the dispatch table rather than
maintained by hand, so the test that matters is the one checking it against main.nut.
"""

from __future__ import annotations

import re

from nttd.constants import KNOWN_ACTIONS, TICK_DEPENDENT_ACTIONS
from nttd.runtime.orchestrator import _needs_game_ticks
from tests.conftest import REPO_ROOT

GAMESCRIPT = REPO_ROOT / "ottd_config/game/nttd-gs/main.nut"


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

    If a new handler starts searching, or connect_rail stops, this fails rather than
    leaving issue #58 with a stale idea of what it has to replace.
    """
    assert _dispatched_names(_yielding_handlers()) == set(TICK_DEPENDENT_ACTIONS)


def test_only_two_actions_out_of_the_whole_surface_need_ticks() -> None:
    assert TICK_DEPENDENT_ACTIONS == {"connect_rail", "connect_road"}
    assert len(KNOWN_ACTIONS) > 70
    assert TICK_DEPENDENT_ACTIONS <= KNOWN_ACTIONS


def test_an_empty_batch_needs_nothing() -> None:
    assert _needs_game_ticks([]) is False
    assert _needs_game_ticks(None) is False


def test_a_batch_of_ordinary_builds_contains_no_search() -> None:
    batch = [
        {"action": "build_rail_station", "params": {"tile": 1}},
        {"action": "build_rail_depot", "params": {"tile": 2}},
        {"action": "buy_vehicle", "params": {"engine_id": 12}},
    ]
    assert _needs_game_ticks(batch) is False


def test_one_pathfinding_action_anywhere_in_the_batch_is_enough() -> None:
    """Length decides whether a search reaches its yield, and that is not knowable
    beforehand, so any batch carrying one is treated as carrying a search."""
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
