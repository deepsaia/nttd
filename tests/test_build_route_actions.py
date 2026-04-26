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


class TestTrackEdge:
    def test_dir0_other_is_east(self) -> None:
        x, y = BuildRouteActions._track_edge(50, 60, 0, 3, 100, 60)
        assert (x, y) == (53, 60)

    def test_dir0_other_is_west(self) -> None:
        x, y = BuildRouteActions._track_edge(50, 60, 0, 3, 10, 60)
        assert (x, y) == (49, 60)

    def test_dir1_other_is_south(self) -> None:
        x, y = BuildRouteActions._track_edge(50, 60, 1, 3, 50, 120)
        assert (x, y) == (50, 63)

    def test_dir1_other_is_north(self) -> None:
        x, y = BuildRouteActions._track_edge(50, 60, 1, 3, 50, 10)
        assert (x, y) == (50, 59)

    def test_dir0_same_x_picks_hi(self) -> None:
        x, y = BuildRouteActions._track_edge(50, 60, 0, 3, 50, 80)
        assert (x, y) == (53, 60)

    def test_dir1_same_y_picks_hi(self) -> None:
        x, y = BuildRouteActions._track_edge(50, 60, 1, 3, 80, 60)
        assert (x, y) == (50, 63)


class TestPlatformEnd:
    def test_dir0_other_east_returns_last_platform(self) -> None:
        x, y = BuildRouteActions._platform_end(50, 60, 0, 3, 100, 60)
        assert (x, y) == (52, 60)

    def test_dir0_other_west_returns_first_platform(self) -> None:
        x, y = BuildRouteActions._platform_end(50, 60, 0, 3, 10, 60)
        assert (x, y) == (50, 60)

    def test_dir1_other_south_returns_last_platform(self) -> None:
        x, y = BuildRouteActions._platform_end(50, 60, 1, 3, 50, 120)
        assert (x, y) == (50, 62)

    def test_dir1_other_north_returns_first_platform(self) -> None:
        x, y = BuildRouteActions._platform_end(50, 60, 1, 3, 50, 10)
        assert (x, y) == (50, 60)

    def test_platform_end_adjacent_to_track_edge(self) -> None:
        """Platform end should be exactly 1 tile inward from track edge."""
        for direction in (0, 1):
            edge_x, edge_y = BuildRouteActions._track_edge(50, 60, direction, 3, 100, 100)
            hint_x, hint_y = BuildRouteActions._platform_end(50, 60, direction, 3, 100, 100)
            assert abs(edge_x - hint_x) + abs(edge_y - hint_y) == 1


class TestTownRouteParams:
    """Tests for town/passenger route parameter handling."""

    def test_town_route_skips_cargo_validation(self) -> None:
        """Town routes should not call _validate_cargo_chain."""
        obs = {
            "industries": [
                {"id": 1, "name": "Coal Mine",
                 "production": [{"cargo_label": "COAL"}], "accepted": []},
            ],
        }
        valid, _ = BuildRouteActions._validate_cargo_chain(1, 999, obs)
        assert valid is True

    def test_industry_and_town_both_none_invalid(self) -> None:
        """Both industry and town IDs missing should be rejected."""
        import asyncio
        import json
        tool = BuildRouteActions()

        async def run() -> str:
            return await tool.async_invoke(
                {"engine_id": 0},
                {"observation": {}, "session_id": "test", "company_id": 0},
            )

        result = json.loads(asyncio.run(run()))
        assert result["success"] is False
        assert "Must provide" in result["error"]


class TestCargoValidation:
    """Tests for _validate_cargo_chain supply-chain checking."""

    @staticmethod
    def _obs(industries: list) -> dict:
        return {"industries": industries}

    def test_valid_chain(self) -> None:
        obs = self._obs([
            {"id": 1, "name": "Coal Mine", "production": [{"cargo_label": "COAL"}], "accepted": []},
            {"id": 2, "name": "Power Station", "production": [], "accepted": [{"cargo_label": "COAL"}]},
        ])
        valid, reason = BuildRouteActions._validate_cargo_chain(1, 2, obs)
        assert valid is True
        assert reason == ""

    def test_mismatched_chain(self) -> None:
        obs = self._obs([
            {"id": 1, "name": "Coal Mine",
             "production": [{"cargo_label": "COAL"}], "accepted": []},
            {"id": 3, "name": "Factory", "production": [],
             "accepted": [{"cargo_label": "STEL"}, {"cargo_label": "GRAI"}]},
        ])
        valid, reason = BuildRouteActions._validate_cargo_chain(1, 3, obs)
        assert valid is False
        assert "Coal Mine" in reason
        assert "Factory" in reason

    def test_missing_industry_allows(self) -> None:
        obs = self._obs([
            {"id": 1, "name": "Coal Mine", "production": [{"cargo_label": "COAL"}], "accepted": []},
        ])
        valid, _ = BuildRouteActions._validate_cargo_chain(1, 999, obs)
        assert valid is True

    def test_no_industries_in_obs(self) -> None:
        valid, _ = BuildRouteActions._validate_cargo_chain(1, 2, {})
        assert valid is True

    def test_multi_cargo_overlap_final_consumer(self) -> None:
        obs = self._obs([
            {"id": 5, "name": "Farm",
             "production": [{"cargo_label": "GRAI"}, {"cargo_label": "LVST"}],
             "accepted": []},
            {"id": 6, "name": "Factory", "production": [],
             "accepted": [{"cargo_label": "GRAI"}, {"cargo_label": "STEL"}]},
        ])
        valid, _ = BuildRouteActions._validate_cargo_chain(5, 6, obs)
        assert valid is True

    def test_rejects_intermediate_processor(self) -> None:
        """Destination that also produces cargo is an intermediate processor."""
        obs = self._obs([
            {"id": 10, "name": "Iron Ore Mine",
             "production": [{"cargo_label": "IORE"}], "accepted": []},
            {"id": 11, "name": "Steel Mill",
             "production": [{"cargo_label": "STEL"}],
             "accepted": [{"cargo_label": "IORE"}]},
        ])
        valid, reason = BuildRouteActions._validate_cargo_chain(10, 11, obs)
        assert valid is False
        assert "intermediate processor" in reason
        assert "Steel Mill" in reason

    def test_allows_final_consumer(self) -> None:
        """Destination with no production is a final consumer (e.g. Power Station)."""
        obs = self._obs([
            {"id": 1, "name": "Coal Mine",
             "production": [{"cargo_label": "COAL"}], "accepted": []},
            {"id": 2, "name": "Power Station",
             "production": [], "accepted": [{"cargo_label": "COAL"}]},
        ])
        valid, _ = BuildRouteActions._validate_cargo_chain(1, 2, obs)
        assert valid is True

    def test_rejects_sawmill_as_intermediate(self) -> None:
        """Sawmill accepts WOOD but produces GOOD -- intermediate processor."""
        obs = self._obs([
            {"id": 20, "name": "Forest",
             "production": [{"cargo_label": "WOOD"}], "accepted": []},
            {"id": 21, "name": "Sawmill",
             "production": [{"cargo_label": "GOOD"}],
             "accepted": [{"cargo_label": "WOOD"}]},
        ])
        valid, reason = BuildRouteActions._validate_cargo_chain(20, 21, obs)
        assert valid is False
        assert "Sawmill" in reason
