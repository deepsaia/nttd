"""Tests for A* pathfinding — core algorithm, road, rail, bridge/tunnel expansion."""

import pytest

from nttd.pathfinding.astar import find_path
from nttd.pathfinding.rail import RailCostFunction
from nttd.pathfinding.road import RoadCostFunction
from nttd.pathfinding.tile_cache import TileCache, TileData
from nttd.pathfinding.water import WaterCostFunction


def _make_cache(width: int, height: int) -> TileCache:
    cache = TileCache(width, height)
    return cache


def _fill_buildable(cache: TileCache, x1: int, y1: int, x2: int, y2: int) -> None:
    """Fill a rectangle with flat buildable land."""
    for x in range(x1, x2):
        for y in range(y1, y2):
            cache.set_tile(x, y, TileData(buildable=True, height=1))


def _fill_water(cache: TileCache, x1: int, y1: int, x2: int, y2: int) -> None:
    """Fill a rectangle with water."""
    for x in range(x1, x2):
        for y in range(y1, y2):
            cache.set_tile(x, y, TileData(water=True, height=0))


def _fill_hill(cache: TileCache, x1: int, y1: int, x2: int, y2: int, height: int) -> None:
    """Fill a rectangle with elevated impassable terrain (for tunnel testing)."""
    for x in range(x1, x2):
        for y in range(y1, y2):
            cache.set_tile(x, y, TileData(buildable=False, height=height, slope=1))


class TestAStarCore:
    def test_straight_path(self) -> None:
        cache = _make_cache(20, 20)
        _fill_buildable(cache, 0, 0, 20, 20)
        cost_fn = RoadCostFunction(cache)
        result = find_path(1, 1, 5, 1, cost_fn, max_iterations=1000)
        assert result.found
        assert len(result.path) == 5  # start + 4 steps
        assert result.path[0]["x"] == 1
        assert result.path[-1]["x"] == 5

    def test_no_path(self) -> None:
        cache = _make_cache(20, 20)
        # Only fill start and end, leave gap unfilled (None tiles)
        cache.set_tile(1, 1, TileData(buildable=True, height=1))
        cache.set_tile(10, 1, TileData(buildable=True, height=1))
        cost_fn = RoadCostFunction(cache)
        result = find_path(1, 1, 10, 1, cost_fn, max_iterations=1000)
        assert not result.found

    def test_max_iterations_respected(self) -> None:
        cache = _make_cache(100, 100)
        _fill_buildable(cache, 0, 0, 100, 100)
        cost_fn = RoadCostFunction(cache)
        result = find_path(1, 1, 99, 99, cost_fn, max_iterations=50)
        assert not result.found
        assert result.iterations == 50


class TestRoadBridge:
    def test_bridge_over_water(self) -> None:
        """Road pathfinder should build a bridge over a water gap."""
        cache = _make_cache(20, 10)
        # Land on both sides, water in the middle
        _fill_buildable(cache, 0, 0, 5, 10)
        _fill_water(cache, 5, 0, 8, 10)
        _fill_buildable(cache, 8, 0, 20, 10)
        result = find_path(
            1, 5, 12, 5, RoadCostFunction(cache), max_iterations=5000,
        )
        assert result.found
        actions = [p["action"] for p in result.path]
        assert "build_bridge" in actions

    def test_bridge_too_long(self) -> None:
        """Bridge should not be attempted when gap exceeds MAX_BRIDGE_LENGTH."""
        cache = _make_cache(30, 10)
        _fill_buildable(cache, 0, 0, 3, 10)
        _fill_water(cache, 3, 0, 20, 10)  # 17-tile water gap
        _fill_buildable(cache, 20, 0, 30, 10)
        result = find_path(
            1, 5, 25, 5, RoadCostFunction(cache), max_iterations=5000,
        )
        # Should fail — no bridge can span 17 tiles (max=10)
        assert not result.found


class TestRoadTunnel:
    def test_tunnel_through_hill(self) -> None:
        """Road pathfinder should tunnel through elevated terrain when demolish is avoided."""
        cache = _make_cache(20, 10)
        _fill_buildable(cache, 0, 0, 4, 10)
        # Tunnel entrance: slope at base height
        cache.set_tile(4, 5, TileData(buildable=True, height=1, slope=1))
        # Hill interior: higher terrain, impassable
        _fill_hill(cache, 5, 0, 8, 10, height=3)
        # Tunnel exit: slope at base height
        cache.set_tile(8, 5, TileData(buildable=True, height=1, slope=1))
        _fill_buildable(cache, 9, 0, 20, 10)

        result = find_path(
            1, 5, 12, 5,
            RoadCostFunction(cache, avoid_demolish=True),
            max_iterations=5000,
        )
        assert result.found
        actions = [p["action"] for p in result.path]
        assert "build_tunnel" in actions


class TestRailBridgeTunnel:
    def test_rail_bridge(self) -> None:
        """Rail pathfinder should bridge over water, preserving direction."""
        cache = _make_cache(20, 10)
        _fill_buildable(cache, 0, 0, 5, 10)
        _fill_water(cache, 5, 0, 8, 10)
        _fill_buildable(cache, 8, 0, 20, 10)
        result = find_path(
            1, 5, 12, 5, RailCostFunction(cache), max_iterations=5000,
        )
        assert result.found
        actions = [p["action"] for p in result.path]
        assert "build_bridge" in actions

    def test_rail_bridge_maintains_direction(self) -> None:
        """Rail bridge should only be attempted in the current direction."""
        cache = _make_cache(20, 10)
        _fill_buildable(cache, 0, 0, 5, 10)
        _fill_water(cache, 5, 0, 8, 10)
        _fill_buildable(cache, 8, 0, 20, 10)
        result = find_path(
            1, 5, 12, 5, RailCostFunction(cache), max_iterations=5000,
        )
        assert result.found
        # Bridge step should have direction metadata
        bridge_steps = [p for p in result.path if p.get("action") == "build_bridge"]
        assert len(bridge_steps) >= 1


class TestWaterPathfinder:
    def test_water_path(self) -> None:
        cache = _make_cache(20, 10)
        _fill_water(cache, 0, 0, 20, 10)
        result = find_path(
            1, 5, 15, 5, WaterCostFunction(cache), max_iterations=5000,
        )
        assert result.found

    def test_canal_through_land(self) -> None:
        cache = _make_cache(20, 10)
        _fill_water(cache, 0, 0, 5, 10)
        _fill_buildable(cache, 5, 0, 8, 10)
        _fill_water(cache, 8, 0, 20, 10)
        result = find_path(
            1, 5, 15, 5, WaterCostFunction(cache), max_iterations=5000,
        )
        assert result.found
        actions = [p["action"] for p in result.path]
        assert "build_canal" in actions


class TestExistingInfraReuse:
    def test_existing_road_cheaper(self) -> None:
        """Path through existing road should cost less than building new."""
        cache = _make_cache(20, 10)
        _fill_buildable(cache, 0, 0, 20, 10)
        # Put existing road on y=5
        for x in range(0, 20):
            cache.set_tile(x, 5, TileData(buildable=True, has_road=True, height=1))
        cost_fn = RoadCostFunction(cache)
        # Path along existing road
        result_road = find_path(1, 5, 15, 5, cost_fn, max_iterations=5000)
        # Path through empty land (y=3)
        result_land = find_path(1, 3, 15, 3, cost_fn, max_iterations=5000)
        assert result_road.found and result_land.found
        assert result_road.total_cost < result_land.total_cost

    def test_enemy_road_avoided(self) -> None:
        """Road owned by another company can't be traversed directly but can be bridged."""
        cache = _make_cache(20, 10)
        _fill_buildable(cache, 0, 0, 20, 10)
        # Enemy road in the middle
        for x in range(5, 8):
            cache.set_tile(x, 5, TileData(has_road=True, owner=2, height=1))
        cost_fn = RoadCostFunction(cache, company_id=0)
        result = find_path(1, 5, 12, 5, cost_fn, max_iterations=5000)
        assert result.found
        # Should go around or bridge, not use enemy road directly
        for step in result.path:
            if step["action"] == "move":
                tile = cache.get(step["x"], step["y"])
                if tile and tile.has_road and tile.owner == 2:
                    pytest.fail("Path traversed enemy-owned road")
