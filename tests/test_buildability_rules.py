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


def test_the_pathfinder_avoids_turning_on_a_slope() -> None:
    """The game refuses many curves on slopes with ERR_LAND_SLOPED_WRONG, so a flat corner
    is worth a long detour.

    Measured: a 37 tile corridor over ground with no water and no height obstacles failed
    on exactly one segment, at (19,40), where the path entered from (19,39) and left to
    (20,40) across a single raised corner, while both neighbours were flat.
    """
    body = _function_body("_FindRailPath")
    assert "turn != 0" in body
    assert "GSTile.GetSlope(cur_tile) != GSTile.SLOPE_FLAT" in body
    assert "C_SLOPED_CURVE" in body


def test_a_sloped_corner_is_priced_and_not_forbidden() -> None:
    """Which curves a slope refuses depends on the slope and the piece, so a blanket ban
    is wrong, and it was also ruinous: it pruned enough of the search that A* exhausted
    50000 iterations and reported no path on corridors that had always connected.

    The penalty has to outweigh a long detour and stay finite.
    """
    body = _function_body("_FindRailPath")
    slope_rule = body[body.index("turn != 0") :][:400]
    assert "continue" not in slope_rule, "a sloped corner must cost, not disqualify"
    assert "turn_cost += C_SLOPED_CURVE" in slope_rule


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
