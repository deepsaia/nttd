"""Check existing rail and road topology in an isolated OpenTTD world."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import httpx
import pytest

from tests.gameplay.test_gs_integration import gs_query, interpret
from tests.gameplay.test_station_cargo_acceptance_live import _SCENARIO

pytestmark = pytest.mark.gs_test


def _build(client: httpx.Client, sid: str, actions: list[dict]) -> list[dict]:
    results = interpret(client, sid, actions, 0)
    assert all(result["status"] == "success" for result in results), results
    return results


def _action(name: str, **parameters: int | str) -> dict:
    return {"action_type": name, "parameters": parameters}


def _site(tiles: dict[tuple[int, int], dict], width: int, height: int) -> tuple[int, int]:
    for x, y in sorted(tiles, key=lambda point: (point[1], point[0])):
        keys = {(xx, yy) for xx in range(x, x + width) for yy in range(y, y + height)}
        if not keys.issubset(tiles):
            continue
        area = [tiles[key] for key in keys]
        if not all(tile["buildable"] and tile["slope"] == 0 for tile in area):
            continue
        if len({tile["height"] for tile in area}) != 1:
            continue
        for key in keys:
            del tiles[key]
        return x, y
    pytest.fail(f"The test map has no clear {width} by {height} flat patch")


def _rail(client: httpx.Client, sid: str, pieces: list[tuple[int, int, int]]) -> None:
    _build(client, sid, [_action("build_rail_track", x=x, y=y, track=track)
                         for x, y, track in pieces])


def _road(client: httpx.Client, sid: str, start: tuple[int, int], end: tuple[int, int]) -> None:
    _build(client, sid, [_action("connect_road", from_x=start[0], from_y=start[1],
                                to_x=end[0], to_y=end[1], max_iterations=500)])


def _span(
    client: httpx.Client, sid: str, tiles: dict, kind: str, tunnel: bool,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]:
    x, top = _site(tiles, 10, 5)
    y = top + 2
    start, end = (x + 1, y), (x + 8, y)
    entrance, exit_tile = (x + 3, y), (x + 5 if tunnel else x + 6, y)
    if tunnel:
        _build(client, sid, [_action("raise_tile", x=x + 4, y=y, slope=15)])
    if kind == "rail":
        approaches = [x + 1, x + 2, *range(exit_tile[0] + 1, x + 9)]
        _rail(client, sid, [(xx, y, 1) for xx in approaches])
    else:
        _road(client, sid, start, (entrance[0] - 1, y))
        _road(client, sid, (exit_tile[0] + 1, y), end)
    action = (_action("build_tunnel", x=entrance[0], y=y, transport_type=kind)
              if tunnel else _action("build_bridge", start_x=entrance[0], start_y=y,
                                      end_x=exit_tile[0], end_y=y, transport_type=kind,
                                      bridge_type=0))
    result = _build(client, sid, [action])[0]
    if tunnel:
        assert result["changed_entities"]["exit_pos"] == list(exit_tile), result
    if kind == "road":
        _road(client, sid, start, entrance)
        _road(client, sid, exit_tile, end)
    return start, end, entrance, exit_tile


def _layouts(client: httpx.Client, sid: str) -> dict:
    area = gs_query(client, sid, "get_tile_area", {
        "x1": 10, "y1": 10, "x2": 130, "y2": 130, "max_tiles": 15000,
    })
    tiles = {(tile["x"], tile["y"]): tile for tile in area
             if not any(tile[name] for name in ("has_rail", "has_road", "is_station",
                                                "is_bridge", "is_tunnel", "water"))}
    layouts = {}
    x, y = _site(tiles, 9, 3)
    y += 1
    _rail(client, sid, [(x + i, y, 1) for i in (0, 1, 2, 5, 7)] + [(x + 3, y, 2)])
    layouts["track"] = [(x + i, y) for i in range(8)]

    x, y = _site(tiles, 7, 7)
    _rail(client, sid, [(x + i, y + 3, 1) for i in range(1, 6)]
          + [(x + 3, y + i, 2) for i in range(1, 6)])
    layouts["crossing"] = [(x + 1, y + 3), (x + 5, y + 3),
                           (x + 3, y + 1), (x + 3, y + 5)]

    x, y = _site(tiles, 7, 5)
    _rail(client, sid, [(x + i, y + 3, 1) for i in (1, 2, 4, 5)]
          + [(x + 3, y + i, 2) for i in (1, 2)] + [(x + 3, y + 3, 4)])
    layouts["curve"] = [(x + 1, y + 3), (x + 3, y + 1), (x + 5, y + 3)]

    x, y = _site(tiles, 9, 3)
    y += 1
    _rail(client, sid, [(x + i, y, 1) for i in (1, 2, 4, 5, 6)])
    _build(client, sid, [_action("build_rail_depot", x=x + 3, y=y, direction=0)])
    layouts["rail_depot"] = [(x + 3, y), (x + 6, y), (x + 2, y)]

    x, y = _site(tiles, 7, 3)
    y += 1
    _rail(client, sid, [(x + i, y, 1) for i in (1, 2)])
    _build(client, sid, [_action("build_rail_depot", x=x + 3, y=y, direction=0)])
    layouts["rail_depot_rear_only"] = [(x + 3, y), (x + 2, y)]

    x, y = _site(tiles, 10, 4)
    _rail(client, sid, [(x + i, y + 2, 1) for i in range(6)])
    result = _build(client, sid, [_action("build_rail_station", x=x + 6, y=y + 1,
                                         direction=0, num_platforms=2, platform_length=2)])[0]
    layouts["rail_station"] = [(x, y + 2), (x + 6, y + 1), (x + 6, y + 2),
                               result["changed_entities"]["station_id"]]

    for kind in ("rail", "road"):
        for tunnel in (False, True):
            layouts[f"{kind}_{'tunnel' if tunnel else 'bridge'}"] = _span(
                client, sid, tiles, kind, tunnel,
            )

    x, y = _site(tiles, 14, 3)
    y += 1
    _rail(client, sid, [(x + i, y, 1) for i in (0, 1, 6, 7, 12, 13)])
    _build(client, sid, [_action("build_bridge", start_x=x + a, start_y=y,
                                 end_x=x + b, end_y=y, transport_type="rail", bridge_type=0)
                         for a, b in ((2, 5), (8, 11))])
    layouts["rail_bridge_chain"] = [(x, y), (x + 13, y)]

    x, y = _site(tiles, 10, 3)
    y += 1
    _road(client, sid, (x + 4, y), (x + 7, y))
    results = _build(client, sid, [
        _action("build_road_depot", x=x + 3, y=y, direction=0),
        _action("build_road_stop", x=x + 8, y=y, direction=2, is_truck_stop=True),
    ])
    _road(client, sid, (x + 3, y), (x + 4, y))
    _road(client, sid, (x + 8, y), (x + 7, y))
    _road(client, sid, (x, y), (x + 2, y))
    layouts["road_depot"] = [(x + 3, y), (x + 8, y), (x + 2, y),
                             results[1]["changed_entities"]["station_id"]]
    return layouts


@pytest.fixture(scope="module")
def topology_world(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[httpx.Client, str, dict]]:
    config = tmp_path_factory.mktemp("route_topology") / "scenario.conf"
    config.write_text(_SCENARIO.replace("wall_minutes = 3.0", "wall_minutes = 6.0"))
    sid = f"route_topology_{uuid.uuid4().hex[:12]}"
    admin = "/v1/operator/admin/sessions"
    with httpx.Client(base_url=request.config.getoption("--base-url"), timeout=60) as client:
        response = client.post(f"{admin}/new", json={"name": sid, "config_path": str(config)})
        response.raise_for_status()
        try:
            response = client.post(f"{admin}/{sid}/start", json={
                "mode": "newgame", "agent_companies": 0, "ai_opponents": 1,
            })
            response.raise_for_status()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                response = client.get(f"/v1/participant/sessions/{sid}/state/full")
                if response.is_success and response.json().get("companies"):
                    break
                time.sleep(0.25)
            else:
                pytest.fail("The isolated test world did not become ready")
            yield client, sid, _layouts(client, sid)
        finally:
            response = client.post(f"{admin}/{sid}/stop")
            response.raise_for_status()


def _trace(
    world: tuple[httpx.Client, str, dict], start: tuple[int, int], end: tuple[int, int],
    kind: str = "rail", **parameters: int,
) -> dict:
    client, sid, _ = world
    result = gs_query(client, sid, "trace_route", {
        "from_x": start[0], "from_y": start[1], "to_x": end[0], "to_y": end[1],
        "transport_type": kind, **parameters,
    })
    assert "line_exists" in result, result
    return result


@pytest.mark.parametrize(("start", "end", "connected"), [
    (0, 2, True), (2, 0, True), (2, 3, False), (3, 2, False),
    (0, 3, False), (3, 0, False), (5, 7, False), (7, 5, False),
])
def test_rail_endpoints_require_matching_track(
    topology_world: tuple, start: int, end: int, connected: bool,
) -> None:
    points = topology_world[2]["track"]
    result = _trace(topology_world, points[start], points[end])
    assert result["line_exists"] is connected and not result["exhausted"], result


@pytest.mark.parametrize(("start", "end", "connected"), [
    (0, 1, True), (2, 3, True), (0, 2, False), (3, 1, False),
])
def test_rail_crossing_does_not_allow_a_missing_turn(
    topology_world: tuple, start: int, end: int, connected: bool,
) -> None:
    points = topology_world[2]["crossing"]
    result = _trace(topology_world, points[start], points[end])
    assert result["line_exists"] is connected, result


@pytest.mark.parametrize(("start", "end", "connected"), [
    (0, 1, True), (1, 0, True), (0, 2, False), (1, 2, False),
])
def test_rail_curve_only_connects_its_two_sides(
    topology_world: tuple, start: int, end: int, connected: bool,
) -> None:
    points = topology_world[2]["curve"]
    result = _trace(topology_world, points[start], points[end])
    assert result["line_exists"] is connected, result


@pytest.mark.parametrize("layout", ["rail_bridge", "rail_tunnel", "road_bridge", "road_tunnel",
                                    "rail_bridge_chain"])
@pytest.mark.parametrize("reverse", [False, True])
def test_bridges_and_tunnels_connect_their_approaches(
    topology_world: tuple, layout: str, reverse: bool,
) -> None:
    start, end = topology_world[2][layout][:2]
    if reverse:
        start, end = end, start
    result = _trace(topology_world, start, end, layout.split("_")[0])
    assert result["line_exists"] is True and not result["exhausted"], result


@pytest.mark.parametrize("kind", ["rail", "road"])
@pytest.mark.parametrize(("start", "end", "connected"), [
    (0, 1, True), (1, 0, True), (0, 2, False), (2, 0, False),
])
def test_depots_only_connect_through_their_entrance(
    topology_world: tuple, kind: str, start: int, end: int, connected: bool,
) -> None:
    points = topology_world[2][f"{kind}_depot"]
    result = _trace(topology_world, points[start], points[end], kind)
    assert result["line_exists"] is connected, result


def test_station_id_can_reach_a_connected_non_anchor_platform(topology_world: tuple) -> None:
    start, anchor, platform, station_id = topology_world[2]["rail_station"]
    assert _trace(topology_world, start, anchor)["line_exists"] is False
    assert _trace(topology_world, start, platform)["line_exists"] is True
    result = _trace(topology_world, start, anchor, to_station_id=station_id)
    assert result["line_exists"] is True, result
    result = _trace(topology_world, anchor, start, from_station_id=station_id)
    assert result["line_exists"] is True, result


def test_station_id_rejects_another_transport_type(topology_world: tuple) -> None:
    start, end, _, road_station = topology_world[2]["road_depot"]
    result = _trace(topology_world, start, end, to_station_id=road_station)
    assert result["line_exists"] is False, result


def test_bounded_search_does_not_claim_disconnection(topology_world: tuple) -> None:
    points = topology_world[2]["track"]
    result = _trace(topology_world, points[0], points[2], max_iterations=1)
    assert result["exhausted"] is True and result["line_exists"] is None, result


def test_connect_depot_cannot_use_a_line_behind_its_door(topology_world: tuple) -> None:
    client, sid, layouts = topology_world
    depot, rear = layouts["rail_depot_rear_only"]
    result = interpret(client, sid, [_action("connect_depot", x=depot[0], y=depot[1])], 0)[0]
    assert result["status"] == "failed", result
    assert "front tile" in result["error"], result
    assert _trace(topology_world, depot, rear)["line_exists"] is False


def test_connect_depot_reports_its_actual_entrance(topology_world: tuple) -> None:
    client, sid, layouts = topology_world
    depot, end, _ = layouts["rail_depot"]
    result = _build(client, sid, [_action("connect_depot", x=depot[0], y=depot[1])])[0]
    assert result["changed_entities"]["joined_at"] == [depot[0] + 1, depot[1]], result
    assert _trace(topology_world, depot, end)["line_exists"] is True


def _path_steps(points: list[tuple[int, int]]) -> list[dict]:
    return [{"x": x, "y": y,
             "action": "start" if index == 0 else "end" if index == len(points) - 1 else "move"}
            for index, (x, y) in enumerate(points)]


@pytest.mark.parametrize("layout", ["track", "rail_bridge", "rail_tunnel"])
def test_build_path_verifies_existing_rail_without_building(topology_world: tuple, layout: str) -> None:
    client, sid, layouts = topology_world
    if layout == "track":
        points = layouts[layout][:3]
    else:
        start, end, entrance, exit_tile = layouts[layout]
        points = [(x, start[1]) for x in range(start[0], entrance[0] + 1)]
        points.extend((x, end[1]) for x in range(exit_tile[0], end[0] + 1))
    result = interpret(client, sid, [{"action_type": "build_path", "parameters": {
        "transport_type": "rail", "steps": _path_steps(points),
    }}], 0)[0]
    assert result["status"] == "success", result
    details = result["changed_entities"]
    assert details["status"] == "complete", details
    assert details["built"] == 0 and details["failed"] == [] and details["gaps"] == [], details


@pytest.mark.parametrize("indices", [(0, 1, 2, 3), (5, 6, 7), (0, 2)])
def test_build_path_reports_disconnected_skipped_steps(topology_world: tuple, indices: tuple[int, ...]) -> None:
    client, sid, layouts = topology_world
    points = [layouts["track"][index] for index in indices]
    result = interpret(client, sid, [{"action_type": "build_path", "parameters": {
        "transport_type": "rail", "steps": _path_steps(points),
    }}], 0)[0]
    assert result["status"] == "partial", result
    assert result["error_name"] == "ROUTE_DISCONTINUOUS", result
    details = result["changed_entities"]
    assert details["status"] == "partial", details
    assert details["built"] == 0 and details["failed"] == [] and details["gaps"], details
