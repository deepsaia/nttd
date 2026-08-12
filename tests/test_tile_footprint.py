"""Which tiles an action may have changed.

This is the arithmetic behind keeping a stored map in step with the world. Getting it wrong
gives a map that quietly disagrees with the game, which is worse than no map at all,
because everything reading it believes it.

Deliberately generous: re-reading a tile that did not change costs one cheap query, while
missing one that did leaves the map claiming ground is empty when a station stands on it.
So these tests check that the real tiles are always inside the answer, not that the answer
is tight.
"""

from __future__ import annotations

from nttd.state.tile_footprint import affected_area

WIDTH = HEIGHT = 256


def _area(action: str, params: dict, changed: dict | None = None):
    return affected_area(action, params, changed, WIDTH, HEIGHT)


def _covers(area, x: int, y: int) -> bool:
    x1, y1, x2, y2 = area
    return x1 <= x <= x2 and y1 <= y <= y2


# ----------------------------------------------------------------------


def test_a_tile_index_is_turned_back_into_coordinates() -> None:
    """Actions take a tile index, and tile = y * map_width + x throughout nttd."""
    area = _area("build_rail_station", {"tile": 58 * WIDTH + 67})
    assert _covers(area, 67, 58)


def test_x_and_y_are_read_when_given_instead() -> None:
    area = _area("build_rail_station", {"x": 67, "y": 58})
    assert _covers(area, 67, 58)


def test_a_station_footprint_is_covered_not_just_its_corner() -> None:
    """A three platform station covers three tiles from the tile it was given, and the
    area is padded rather than modelling each footprint, which would be one more copy of
    the game's rules to keep in step."""
    area = _area(
        "build_rail_station",
        {"tile": 184 * WIDTH + 76, "num_platforms": 1, "platform_length": 3},
    )
    for offset in range(3):
        assert _covers(area, 76 + offset, 184)


def test_both_ends_of_a_connection_are_covered() -> None:
    area = _area("connect_rail", {
        "tile_from": 184 * WIDTH + 76, "tile_to": 155 * WIDTH + 73,
    })
    assert _covers(area, 76, 184)
    assert _covers(area, 73, 155)
    assert _covers(area, 74, 170), "the corridor between the ends is inside the box"


def test_what_a_compound_build_reported_is_covered() -> None:
    """connect_rail names every segment it laid and every gap it left, and those are the
    tiles that changed whatever was asked for."""
    area = _area(
        "connect_rail",
        {"tile_from": 100, "tile_to": 200},
        {"failed": [{"x": 78, "y": 177}], "gaps": [{"x": 78, "y": 174}]},
    )
    assert _covers(area, 78, 177)
    assert _covers(area, 78, 174)


def test_a_build_paths_own_steps_are_covered() -> None:
    area = _area("build_path", {"steps": [
        {"x": 10, "y": 10, "action": "rail"},
        {"x": 40, "y": 40, "action": "rail"},
    ]})
    assert _covers(area, 10, 10)
    assert _covers(area, 40, 40)


def test_a_depot_tile_is_covered() -> None:
    area = _area("buy_vehicle", {"depot_tile": 180 * WIDTH + 77, "engine_id": 12})
    assert _covers(area, 77, 180)


def test_terraforming_gets_more_slack_than_a_build() -> None:
    """Levelling spills onto neighbours in a way placing a building does not.

    The names are checked against KNOWN_ACTIONS by the test below, because a padded set
    listing an action that does not exist would silently do nothing.
    """
    build = _area("build_rail_station", {"x": 100, "y": 100})
    level = _area("level_tiles", {"x": 100, "y": 100})
    assert (level[2] - level[0]) > (build[2] - build[0])


def test_an_action_naming_no_tile_asks_for_nothing() -> None:
    """Most of the surface is not about tiles. start_vehicle should not trigger a read."""
    assert _area("start_vehicle", {"vehicle_id": 8}) is None
    assert _area("set_loan", {"amount": 1000}) is None


def test_an_unknown_action_asks_for_nothing() -> None:
    assert _area("teleport_vehicle", {"tile": 500}) is None


def test_a_read_only_query_asks_for_nothing() -> None:
    """Queries change nothing, so refreshing after one is pure waste."""
    assert _area("get_tile_info", {"tile": 500}) is None


def test_the_area_never_leaves_the_map() -> None:
    """Tiles run 1 to size minus two, and a request outside that is refused by the game."""
    for params in ({"x": 1, "y": 1}, {"x": 254, "y": 254}):
        x1, y1, x2, y2 = _area("build_rail_station", params)
        assert x1 >= 1 and y1 >= 1
        assert x2 <= WIDTH - 2 and y2 <= HEIGHT - 2


def test_a_flag_parameter_is_not_mistaken_for_a_coordinate() -> None:
    """isinstance(True, int) is true in Python, so keep_rail would otherwise read as 1."""
    area = _area("remove_rail_station", {"x": 50, "y": 60, "keep_rail": True})
    assert _covers(area, 50, 60)
    assert not _covers(area, 1, 1)


def test_a_negative_tile_index_is_ignored() -> None:
    assert _area("build_rail_station", {"tile": -5}) is None


def test_the_terraforming_names_are_real_actions() -> None:
    """A set naming actions that do not exist would silently never apply."""
    from nttd.constants import KNOWN_ACTIONS
    from nttd.state.tile_footprint import _TERRAFORMING

    assert _TERRAFORMING <= KNOWN_ACTIONS
