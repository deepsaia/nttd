"""Tests for find_unserved_routes observation format handling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "neuro_san_mas" / "coded_tools"))

from rail_mas.find_unserved_routes import FindUnservedRoutes  # noqa: E402


class TestNormalizeRoute:
    def test_compact_fields_mapped(self) -> None:
        route = {
            "src_id": 1, "dst_id": 2, "src": "Mine", "dst": "Station",
            "dist": 50, "prod": 100, "src_x": 10, "src_y": 20,
            "dst_x": 60, "dst_y": 70, "cargo": "COAL",
        }
        result = FindUnservedRoutes._normalize_route(route)
        assert result["source_id"] == 1
        assert result["dest_id"] == 2
        assert result["source_name"] == "Mine"
        assert result["dest_name"] == "Station"
        assert result["distance"] == 50
        assert result["monthly_production"] == 100
        assert result["source_x"] == 10
        assert result["dest_x"] == 60

    def test_full_fields_unchanged(self) -> None:
        route = {
            "source_id": 1, "dest_id": 2, "source_name": "Mine", "dest_name": "Station",
            "distance": 50, "monthly_production": 100,
            "source_x": 10, "source_y": 20, "dest_x": 60, "dest_y": 70,
            "cargo": "COAL",
        }
        result = FindUnservedRoutes._normalize_route(dict(route))
        assert result["source_id"] == 1
        assert result["dest_id"] == 2
        assert "src_id" not in result or result.get("source_id") == 1

    def test_full_fields_not_overwritten_by_compact(self) -> None:
        route = {
            "src_id": 99, "source_id": 1,
            "dst_id": 88, "dest_id": 2,
        }
        result = FindUnservedRoutes._normalize_route(route)
        assert result["source_id"] == 1
        assert result["dest_id"] == 2
