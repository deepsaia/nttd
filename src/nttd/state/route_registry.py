"""Persistent route registry: assigns stable IDs and tracks lifecycle.

Routes are identified by a deterministic hash of (company_id, vehicle_type, sorted station_ids).
The registry reconciles each cycle from live vehicle orders, and updates status from action results.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nttd.schemas.route import Route, make_route_id

if TYPE_CHECKING:
    from nttd.schemas.station import Station
    from nttd.schemas.vehicle import Vehicle

logger = logging.getLogger(__name__)


class RouteRegistry:

    def __init__(self) -> None:
        self._routes: dict[str, Route] = {}

    def reconcile(
        self,
        vehicles: dict[int, Vehicle],
        stations: dict[int, Station],
        game_date: int,
    ) -> list[Route]:
        """Reconcile registry with live vehicle/station data. Returns all routes."""
        active_route_ids: set[str] = set()

        vehicle_groups: dict[tuple[int, str, tuple[int, ...]], list[Vehicle]] = {}
        for v in vehicles.values():
            sids = tuple(o.destination for o in v.orders if o.is_goto_station)
            if not sids:
                continue
            key = (v.company_id, v.type, sids)
            vehicle_groups.setdefault(key, []).append(v)

        for (company_id, vtype, sids), vlist in vehicle_groups.items():
            rid = make_route_id(company_id, vtype, sids)
            active_route_ids.add(rid)

            if rid in self._routes:
                route = self._routes[rid]
            else:
                route = Route(
                    route_id=rid,
                    company_id=company_id,
                    vehicle_type=vtype,
                    station_ids=list(sids),
                    status="active",
                    created_at=game_date,
                    first_vehicle_at=game_date,
                )
                self._routes[rid] = route
                logger.info("Route %s created (active): stations %s", rid, list(sids))

            route.vehicle_ids = [v.id for v in vlist]
            route.vehicle_count = len(vlist)
            route.total_profit_this_year = sum(v.profit_this_year for v in vlist)
            route.total_profit_last_year = sum(v.profit_last_year for v in vlist)
            if route.status == "planned" or route.status == "track_built":
                route.status = "active"
                route.first_vehicle_at = route.first_vehicle_at or game_date

        for rid, route in self._routes.items():
            if rid not in active_route_ids and route.status == "active":
                all_stations_exist = all(
                    sid in stations for sid in route.station_ids
                )
                if all_stations_exist:
                    route.status = "track_built"
                    route.vehicle_ids = []
                    route.vehicle_count = 0
                    route.total_profit_this_year = 0
                    route.total_profit_last_year = 0
                else:
                    route.status = "removed"

        return [r for r in self._routes.values() if r.status != "removed"]

    def on_action_result(
        self,
        action_type: str,
        params: dict[str, Any],
        result: dict[str, Any],
        stations: dict[int, Station],
        game_date: int,
    ) -> None:
        """Process a successful action result to update route associations."""
        if action_type == "connect_rail":
            self._handle_connect_rail(params, stations, game_date)
        elif action_type == "build_rail_depot":
            self._handle_depot(params, stations)
        elif action_type in ("build_train", "buy_vehicle"):
            self._handle_vehicle_buy(params, result)

    def _handle_connect_rail(
        self,
        params: dict[str, Any],
        stations: dict[int, Station],
        game_date: int,
    ) -> None:
        from_x = params.get("from_x", 0)
        from_y = params.get("from_y", 0)
        to_x = params.get("to_x", 0)
        to_y = params.get("to_y", 0)

        src_sid = _find_station_near(from_x, from_y, stations)
        dst_sid = _find_station_near(to_x, to_y, stations)
        if src_sid is None or dst_sid is None:
            return

        for route in self._routes.values():
            if route.status != "planned":
                continue
            route_sids = set(route.station_ids)
            if {src_sid, dst_sid} == route_sids:
                route.status = "track_built"
                route.track_confirmed_at = game_date
                logger.info("Route %s: track confirmed", route.route_id)
                return

        rid = make_route_id(0, "train", (src_sid, dst_sid))
        if rid not in self._routes:
            self._routes[rid] = Route(
                route_id=rid,
                company_id=0,
                vehicle_type="train",
                station_ids=[src_sid, dst_sid],
                status="track_built",
                created_at=game_date,
                track_confirmed_at=game_date,
            )
            logger.info("Route %s created from connect_rail: stations [%d, %d]", rid, src_sid, dst_sid)

    def _handle_depot(
        self,
        params: dict[str, Any],
        stations: dict[int, Station],
    ) -> None:
        tile = params.get("tile", 0)
        if tile <= 0:
            return
        route = self._find_route_near_tile(tile, stations)
        if route and route.depot_tile == 0:
            route.depot_tile = tile
            logger.info("Route %s: depot at tile %d", route.route_id, tile)

    def _handle_vehicle_buy(
        self,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        vid = result.get("vehicle_id")
        if vid is None:
            return
        depot_tile = params.get("depot_tile", 0)
        if depot_tile <= 0:
            return
        for route in self._routes.values():
            if route.depot_tile == depot_tile:
                if vid not in route.vehicle_ids:
                    route.vehicle_ids.append(vid)
                    route.vehicle_count = len(route.vehicle_ids)
                    if not route.first_vehicle_at:
                        route.first_vehicle_at = 0
                    logger.info("Route %s: vehicle %d linked via depot %d", route.route_id, vid, depot_tile)
                return

    def _find_route_near_tile(
        self,
        tile: int,
        stations: dict[int, Station],
        max_dist: int = 15,
    ) -> Route | None:
        best_route: Route | None = None
        best_dist = max_dist + 1
        for route in self._routes.values():
            if route.status == "removed":
                continue
            for sid in route.station_ids:
                station = stations.get(sid)
                if station is None:
                    continue
                map_width = 256
                tx = tile % map_width
                ty = tile // map_width
                dist = abs(station.x - tx) + abs(station.y - ty)
                if dist < best_dist:
                    best_dist = dist
                    best_route = route
        return best_route

    def register_planned_route(
        self,
        company_id: int,
        vehicle_type: str,
        station_ids: list[int],
        game_date: int,
    ) -> Route:
        """Register a planned route from orphan station pairs."""
        rid = make_route_id(company_id, vehicle_type, tuple(station_ids))
        if rid in self._routes:
            return self._routes[rid]
        route = Route(
            route_id=rid,
            company_id=company_id,
            vehicle_type=vehicle_type,
            station_ids=station_ids,
            status="planned",
            created_at=game_date,
        )
        self._routes[rid] = route
        logger.info("Route %s registered (planned): stations %s", rid, station_ids)
        return route

    def get_route(self, route_id: str) -> Route | None:
        return self._routes.get(route_id)

    def get_routes(self, company_id: int | None = None) -> list[Route]:
        routes = [r for r in self._routes.values() if r.status != "removed"]
        if company_id is not None:
            routes = [r for r in routes if r.company_id == company_id]
        return routes

    def route_for_vehicle(self, vehicle_id: int) -> Route | None:
        for route in self._routes.values():
            if vehicle_id in route.vehicle_ids:
                return route
        return None

    def routes_for_station(self, station_id: int) -> list[Route]:
        return [
            r for r in self._routes.values()
            if station_id in r.station_ids and r.status != "removed"
        ]


def _find_station_near(
    x: int, y: int, stations: dict[int, Station], max_dist: int = 5,
) -> int | None:
    """Find station ID nearest to (x, y) within max_dist Manhattan distance."""
    best_sid: int | None = None
    best_dist = max_dist + 1
    for sid, s in stations.items():
        dist = abs(s.x - x) + abs(s.y - y)
        if dist < best_dist:
            best_dist = dist
            best_sid = sid
    return best_sid
