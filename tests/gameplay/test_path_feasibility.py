"""Reporting what a connection would take, before an agent pays to find out.

Every other build decision has a dry run behind it: the find_* family answers whether a
station fits by dry running the real build. Connection had none, and it is the step that
decides whether a route earns anything at all. One hand-played attempt cost 6729 for a line
that then reported partial.

These tests cover the shaping of the answer rather than the pathfinder, which has its own.
The shaping is where it went wrong once already: a water route across dry land reported
connected, because the planner is willing to dig canals the whole way, and read as "a ship
can sail here".
"""

from __future__ import annotations

from nttd.api.observation_routes import _work


def test_work_counts_each_kind_of_construction() -> None:
    """The measured rail answer for a real corridor: 31 tiles of track and one bridge."""
    path = (
        [{"action": "build_rail"}] * 31
        + [{"action": "build_bridge"}]
    )
    assert _work(path) == {"build_rail": 31, "build_bridge": 1}


def test_a_water_route_over_land_shows_the_digging() -> None:
    """The case that made the answer misleading. Measured live: 26 canals and 7 tiles of
    existing water, reported as simply connected before this."""
    path = [{"action": "build_canal"}] * 26 + [{"action": "move"}] * 7
    counts = _work(path)
    assert counts["build_canal"] == 26
    assert counts["move"] == 7


def test_the_endpoints_of_the_path_are_not_counted_as_work() -> None:
    """The planner marks its first and last node start and end, and neither is a build."""
    path = [
        {"action": "start"},
        {"action": "build_rail"},
        {"action": "end"},
    ]
    assert _work(path) == {"build_rail": 1}


def test_a_step_with_no_action_counts_as_traversal() -> None:
    assert _work([{}, {}]) == {"move": 2}


def test_an_empty_path_needs_no_work() -> None:
    assert _work([]) == {}


def test_a_route_over_existing_track_is_distinguishable_from_a_new_one() -> None:
    """A line that is mostly there already is a different proposition from one that is
    mostly digging, and that is the judgement the field exists to support."""
    mostly_built = _work([{"action": "move"}] * 30 + [{"action": "build_rail"}])
    mostly_new = _work([{"action": "build_rail"}] * 30 + [{"action": "move"}])
    assert mostly_built["move"] > mostly_built.get("build_rail", 0)
    assert mostly_new["build_rail"] > mostly_new.get("move", 0)
