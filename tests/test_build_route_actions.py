"""Tests for build_route_actions station direction logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.build_route_actions import BuildRouteActions  # noqa: E402


class TestPreferredDirection:
    def test_horizontal_route_picks_ne_sw(self) -> None:
        src = {"x": 50, "y": 60}
        dst = {"x": 120, "y": 65}
        assert BuildRouteActions._preferred_direction(src, dst) == 0

    def test_vertical_route_picks_nw_se(self) -> None:
        src = {"x": 50, "y": 60}
        dst = {"x": 55, "y": 140}
        assert BuildRouteActions._preferred_direction(src, dst) == 1

    def test_diagonal_equal_picks_ne_sw(self) -> None:
        src = {"x": 50, "y": 60}
        dst = {"x": 80, "y": 90}
        assert BuildRouteActions._preferred_direction(src, dst) == 0

    def test_same_tile_picks_ne_sw(self) -> None:
        src = {"x": 50, "y": 60}
        dst = {"x": 50, "y": 60}
        assert BuildRouteActions._preferred_direction(src, dst) == 0


class TestPickDirection:
    def test_preferred_available(self) -> None:
        spot = {"valid_directions": [0, 1]}
        assert BuildRouteActions._pick_direction(spot, 1) == 1

    def test_preferred_unavailable_falls_back(self) -> None:
        spot = {"valid_directions": [1]}
        assert BuildRouteActions._pick_direction(spot, 0) == 1

    def test_no_valid_directions_field(self) -> None:
        spot = {}
        assert BuildRouteActions._pick_direction(spot, 1) == 1

    def test_empty_valid_directions(self) -> None:
        spot = {"valid_directions": []}
        assert BuildRouteActions._pick_direction(spot, 0) == 0
