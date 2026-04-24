"""Cargo-to-wagon matching utility for rail_mas agents."""

from __future__ import annotations

from typing import Any, Optional


class CargoMatcher:
    """Selects the best wagon for a cargo label from the engine list."""

    @staticmethod
    def select_wagon(
        cargo_label: str,
        engines: list[dict[str, Any]],
        rail_type: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Find best wagon matching cargo_label. Prefer highest capacity."""
        wagons = [e for e in engines if e.get("is_wagon")]
        if rail_type is not None:
            wagons = [w for w in wagons if w.get("rail_type") == rail_type]
        matches = [w for w in wagons if w.get("cargo_label") == cargo_label]
        if matches:
            return max(matches, key=lambda w: w.get("capacity", 0))
        return None

    @staticmethod
    def select_engine(
        engines: list[dict[str, Any]],
        rail_type: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Pick cheapest locomotive (is_wagon=false, power > 0)."""
        locos = [
            e for e in engines
            if not e.get("is_wagon") and e.get("power", 0) > 0
        ]
        if rail_type is not None:
            locos = [e for e in locos if e.get("rail_type") == rail_type]
        if locos:
            return min(locos, key=lambda e: e.get("price", float("inf")))
        return None

    @staticmethod
    def get_station_cargo(
        station_id: int, stations: list[dict[str, Any]],
    ) -> Optional[str]:
        """Return primary cargo label for a station from observation data.

        Priority: producing cargo > waiting cargo > accepted cargo.
        """
        for s in stations:
            if s.get("id") != station_id:
                continue
            for ca in s.get("cargo_acceptance", []):
                if ca.get("produces"):
                    return ca.get("cargo_label")
            for cw in s.get("cargo_waiting", []):
                if cw.get("waiting", 0) > 0:
                    return cw.get("cargo_label")
            for ca in s.get("cargo_acceptance", []):
                if ca.get("accepts"):
                    return ca.get("cargo_label")
        return None

    @staticmethod
    def get_pair_cargo(
        src_id: int,
        dst_id: int,
        stations: list[dict[str, Any]],
    ) -> Optional[str]:
        """Determine cargo for a station pair. Producing station's cargo wins."""
        for sid in (src_id, dst_id):
            cargo = CargoMatcher.get_station_cargo(sid, stations)
            if cargo:
                return cargo
        return None

    @staticmethod
    def cargo_label_to_id(
        cargo_label: str, engines: list[dict[str, Any]],
    ) -> Optional[int]:
        """Map cargo label to numeric cargo_type by finding a matching engine."""
        for e in engines:
            if e.get("cargo_label") == cargo_label and e.get("cargo_type") is not None:
                return e["cargo_type"]
        return None
