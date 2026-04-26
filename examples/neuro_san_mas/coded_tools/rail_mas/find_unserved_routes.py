"""Coded tool: find_unserved_routes -- returns unserved cargo and town routes from observation."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)

STATION_CATCHMENT = 10
MAX_ACTIVE_ROUTES = 3

_COMPACT_TO_FULL: Dict[str, str] = {
    "src_id": "source_id",
    "dst_id": "dest_id",
    "src": "source_name",
    "dst": "dest_name",
    "dist": "distance",
    "prod": "monthly_production",
    "src_x": "source_x",
    "src_y": "source_y",
    "dst_x": "dest_x",
    "dst_y": "dest_y",
}

_COMPACT_TOWN_TO_FULL: Dict[str, str] = {
    "a_id": "town_a_id",
    "b_id": "town_b_id",
    "a": "town_a_name",
    "b": "town_b_name",
    "dist": "distance",
    "a_x": "town_a_x",
    "a_y": "town_a_y",
    "b_x": "town_b_x",
    "b_y": "town_b_y",
}


class FindUnservedRoutes(CodedTool):
    """Returns unserved cargo and town routes not near existing stations."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"routes": [], "town_routes": [], "reason": "No observation available."})

        route_status: Dict[str, Any] = obs.get("route_status", {})
        orphan_count = route_status.get("orphan_stations", 0)
        vehicles: List[Dict[str, Any]] = obs.get("vehicles", [])
        running_with_orders = [
            v for v in vehicles
            if v.get("order_count", 0) >= 2 and not v.get("in_depot", False)
        ]

        if orphan_count > 0 and not running_with_orders:
            return json.dumps({
                "routes": [],
                "town_routes": [],
                "reason": (
                    f"{orphan_count} orphan stations and no running vehicles yet. "
                    "Complete the first route before expanding."
                ),
            })

        if vehicles and not running_with_orders:
            return json.dumps({
                "routes": [],
                "town_routes": [],
                "reason": "No vehicles running with orders yet. Expansion deferred.",
            })

        station_actions = [
            a for a in sly_data.get("action_list", [])
            if a.get("action_type") == "build_rail_station"
        ]
        if len(station_actions) >= 2:
            return json.dumps({
                "routes": [],
                "town_routes": [],
                "reason": "Already building a route this cycle.",
            })

        active_routes = [r for r in obs.get("routes", []) if r.get("vehicle_count", 0) >= 1]
        orphan_pair_count = orphan_count // 2
        total_in_flight = len(active_routes) + orphan_pair_count
        if total_in_flight >= MAX_ACTIVE_ROUTES:
            any_profitable = any(
                r.get("profit_this_year", 0) > 0 or r.get("profit_last_year", 0) > 0
                for r in active_routes
            )
            if not any_profitable:
                return json.dumps({
                    "routes": [],
                    "town_routes": [],
                    "reason": (
                        f"{len(active_routes)} active routes + {orphan_pair_count} "
                        f"in-progress (orphan stations), none profitable yet. "
                        "Complete existing routes before expanding."
                    ),
                })

        route_planning: Dict[str, Any] = obs.get("route_planning", {})

        cargo_routes = self._get_cargo_routes(route_planning, obs)
        town_routes = self._get_town_routes(route_planning, obs)

        return json.dumps({"routes": cargo_routes, "town_routes": town_routes})

    def _get_cargo_routes(
        self, route_planning: Dict[str, Any], obs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Filter and return unserved cargo routes (simple chains only)."""
        unserved: List[Dict[str, Any]] = (
            route_planning.get("top_unserved_cargo")
            or route_planning.get("top_cargo", [])
        )
        if not unserved:
            return []

        unserved = [self._normalize_route(r) for r in unserved]
        unserved = self._filter_intermediate_destinations(unserved, obs)
        station_locs = self._all_station_locs(obs)
        served_locs = self._served_station_locs(obs)

        return self._filter_near_stations(unserved, station_locs, served_locs, cargo=True)

    def _get_town_routes(
        self, route_planning: Dict[str, Any], obs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Filter and return unserved town/passenger routes."""
        unserved: List[Dict[str, Any]] = (
            route_planning.get("top_unserved_towns")
            or route_planning.get("top_towns", [])
        )
        if not unserved:
            return []

        unserved = [self._normalize_town_route(r) for r in unserved]
        station_locs = self._all_station_locs(obs)
        served_locs = self._served_station_locs(obs)

        return self._filter_near_stations(unserved, station_locs, served_locs, cargo=False)

    def _filter_near_stations(
        self,
        routes: List[Dict[str, Any]],
        station_locs: List[Tuple[int, int]],
        served_locs: List[Tuple[int, int]],
        cargo: bool,
    ) -> List[Dict[str, Any]]:
        """Remove routes where either endpoint is near an existing station."""
        if cargo:
            src_x_key, src_y_key = "source_x", "source_y"
            dst_x_key, dst_y_key = "dest_x", "dest_y"
        else:
            src_x_key, src_y_key = "town_a_x", "town_a_y"
            dst_x_key, dst_y_key = "town_b_x", "town_b_y"

        available: List[Dict[str, Any]] = []
        for route in routes:
            sx = route.get(src_x_key, 0)
            sy = route.get(src_y_key, 0)
            dx = route.get(dst_x_key, 0)
            dy = route.get(dst_y_key, 0)
            near_existing = any(
                abs(ex - sx) + abs(ey - sy) <= STATION_CATCHMENT
                or abs(ex - dx) + abs(ey - dy) <= STATION_CATCHMENT
                for ex, ey in station_locs
            )
            if near_existing:
                continue
            src_served = any(
                abs(ex - sx) + abs(ey - sy) <= STATION_CATCHMENT
                for ex, ey in served_locs
            )
            dst_served = any(
                abs(ex - dx) + abs(ey - dy) <= STATION_CATCHMENT
                for ex, ey in served_locs
            )
            if src_served and dst_served:
                continue
            available.append(route)
        return available

    @staticmethod
    def _filter_intermediate_destinations(
        routes: List[Dict[str, Any]], obs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Remove routes where the destination is an intermediate processor.

        An intermediate processor is an industry that both accepts AND produces
        cargo (e.g. Steel Mill accepts IORE, produces STEL). Final consumers
        like Power Station accept cargo but produce nothing.

        This ensures we only build simple 2-station chains, not legs of a
        multi-step supply chain. Works across all climates by reading actual
        industry production data from the observation.
        """
        industries = {i["id"]: i for i in obs.get("industries", [])}
        if not industries:
            return routes
        result: List[Dict[str, Any]] = []
        for route in routes:
            dst_id = route.get("dest_id")
            if dst_id is None:
                result.append(route)
                continue
            dst = industries.get(dst_id)
            if dst is None:
                result.append(route)
                continue
            dst_production = [
                p for p in dst.get("production", [])
                if p.get("cargo_label")
            ]
            if dst_production:
                logger.debug(
                    "Skipping route to %s (id=%d): intermediate processor, produces %s",
                    dst.get("name", "?"), dst_id,
                    [p["cargo_label"] for p in dst_production],
                )
                continue
            result.append(route)
        return result

    @staticmethod
    def _all_station_locs(obs: Dict[str, Any]) -> List[Tuple[int, int]]:
        """All station coordinates."""
        return [(s.get("x", 0), s.get("y", 0)) for s in obs.get("stations", [])]

    @staticmethod
    def _normalize_route(route: Dict[str, Any]) -> Dict[str, Any]:
        """Map compact short field names to full names for consistent output."""
        for short, full in _COMPACT_TO_FULL.items():
            if short in route and full not in route:
                route[full] = route[short]
        return route

    @staticmethod
    def _normalize_town_route(route: Dict[str, Any]) -> Dict[str, Any]:
        """Map compact town route field names to full names."""
        for short, full in _COMPACT_TOWN_TO_FULL.items():
            if short in route and full not in route:
                route[full] = route[short]
        return route

    def _served_station_locs(
        self, obs: Dict[str, Any],
    ) -> List[Tuple[int, int]]:
        """Station coordinates for routes that already have at least 1 vehicle."""
        stations_by_id: Dict[int, Dict[str, Any]] = {
            s.get("id", -1): s for s in obs.get("stations", [])
        }
        locs: List[Tuple[int, int]] = []
        for route in obs.get("routes", []):
            if route.get("vehicle_count", 0) < 1:
                continue
            for sid in route.get("station_ids", []):
                s = stations_by_id.get(sid)
                if s:
                    locs.append((s.get("x", 0), s.get("y", 0)))
        return locs
