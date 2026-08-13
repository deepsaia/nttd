"""Rules the game enforces that the planners used to ignore.

Both of these produced work that looked fine and could not be used. They are asserted
against the GameScript source because the rules live in Squirrel.
"""

from __future__ import annotations

from pathlib import Path

GAMESCRIPT = Path(__file__).resolve().parents[1] / "ottd_config" / "game" / "nttd-gs" / "main.nut"


def _function_body(name: str) -> str:
    """The source of one Squirrel function, from its header to the next one."""
    source = GAMESCRIPT.read_text()
    start = source.index(f"function {name}(")
    rest = source[start + 1 :]
    end = rest.find("\n  function ")
    return rest if end == -1 else rest[:end]


def test_the_pathfinder_will_not_turn_on_a_slope() -> None:
    """A curve on a slope is refused by the game with ERR_LAND_SLOPED_WRONG, so a path
    that plans one is unbuildable rather than merely expensive.

    Measured: a 37 tile corridor over ground with no water and no height obstacles failed
    on exactly one segment, at (19,40), where the path entered from (19,39) and left to
    (20,40) across a single raised corner.
    """
    body = _function_body("_FindRailPath")
    assert "turn != 0" in body
    assert "GSTile.GetSlope(cur_tile) != GSTile.SLOPE_FLAT" in body


def test_the_slope_rule_does_not_apply_to_the_seeded_start() -> None:
    """The start is pushed with all four directions, so a turn there is measured against
    an approach the train never made."""
    body = _function_body("_FindRailPath")
    turn_check = body.index("turn != 0")
    assert "came_from[cur_key] != -1" in body[turn_check : turn_check + 200]


def test_a_depot_is_never_offered_against_a_station_platform() -> None:
    """A platform is a line with an axis. A depot opening onto its flank builds, reports
    connected false, and can never release a vehicle."""
    body = _function_body("CmdFindRailDepotSpot")
    assert "GSRail.IsRailStationTile(front)" in body


def test_every_adjacent_track_is_tried_for_a_depot() -> None:
    """adj[0] is whichever direction the scan reached first. A tile with one unusable
    neighbour and one good one used to be discarded on the strength of the wrong one."""
    body = _function_body("CmdFindRailDepotSpot")
    assert "foreach (candidate in adj)" in body
    assert "adj[0]" not in body
