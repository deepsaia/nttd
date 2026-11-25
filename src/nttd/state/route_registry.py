"""Persistent route registry: assigns stable IDs and tracks lifecycle.

Routes are identified by a deterministic hash of (company_id, vehicle_type, sorted station_ids).
The registry reconciles each cycle from live vehicle orders, records the game's answer about
the path between the stations, and updates status from action results.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nttd.schemas.route import Route, make_route_id
from nttd.state.connection_check import ConnectionCheck

if TYPE_CHECKING:
    from nttd.schemas.station import Station
    from nttd.schemas.vehicle import Vehicle

logger = logging.getLogger(__name__)
CheckKey = tuple[str, str, int, int]


class RouteRegistry:

    # About a minute in the realtime benchmark. Mutations invalidate sooner.
    CONNECTION_CACHE_DAYS = 30
    RETRY_INITIAL_DAYS = 5
    RETRY_MAX_DAYS = 30

    def __init__(self) -> None:
        self._routes: dict[str, Route] = {}
        self._map_width: int = 256
        # Successful vehicle walks share the route's bounded confirmation lifetime.
        self._vehicles_with_path: dict[str, set[int]] = {}
        self._vehicle_orders: dict[int, tuple] = {}
        self._station_locations: dict[int, tuple[int, int]] = {}
        # The game hands a sold vehicle's id to the next one bought. A drop in a vehicle's
        # age means a new vehicle under an old id, whose path has to be walked afresh.
        self._vehicle_age: dict[int, int] = {}
        self._connection_checks: dict[CheckKey, ConnectionCheck] = {}
        self._last_checked_route = ""
        self.connection_generation = 0

    def reconcile(
        self,
        vehicles: dict[int, Vehicle],
        stations: dict[int, Station],
        game_date: int,
        map_width: int = 256,
    ) -> list[Route]:
        """Reconcile registry with live vehicle/station data. Returns all routes.

        This groups vehicle orders into routes and nothing more. Whether a path exists
        between the stations is a separate question, answered by record_connection once
        the game has walked the built road or rail.
        """
        self._map_width = map_width
        active_route_ids: set[str] = set()

        locations = {sid: (s.x, s.y) for sid, s in stations.items()}
        if locations != self._station_locations:
            self.invalidate_connections()
        self._station_locations = locations

        for vid, v in vehicles.items():
            orders = tuple((o.destination, o.flags, o.is_goto_station, o.is_goto_depot,
                            o.is_goto_waypoint, o.is_conditional) for o in v.orders)
            if ((self._routes and vid not in self._vehicle_orders)
                    or v.age < self._vehicle_age.get(vid, v.age)
                    or orders != self._vehicle_orders.get(vid, orders)):
                for passed in self._vehicles_with_path.values():
                    passed.discard(vid)
                self.invalidate_connections()
            self._vehicle_age[vid] = v.age
            self._vehicle_orders[vid] = orders
        for vid in [vid for vid in self._vehicle_age if vid not in vehicles]:
            del self._vehicle_age[vid]
            self._vehicle_orders.pop(vid, None)
            for passed in self._vehicles_with_path.values():
                passed.discard(vid)

        tile_to_sid: dict[int, int] = {}
        for sid, s in stations.items():
            tile_to_sid[s.y * map_width + s.x] = sid

        vehicle_groups: dict[tuple[int, str, tuple[int, ...]], list[Vehicle]] = {}
        for v in vehicles.values():
            sids = tuple(
                tile_to_sid[o.destination]
                for o in v.orders
                if o.is_goto_station and o.destination in tile_to_sid
            )
            if not sids:
                continue
            key = (v.company_id, v.type, tuple(sorted(set(sids))))
            vehicle_groups.setdefault(key, []).append(v)

        for (company_id, vtype, sids), vlist in vehicle_groups.items():
            rid = make_route_id(company_id, vtype, sids)
            active_route_ids.add(rid)

            route = self._routes.get(rid)
            if route is None or route.status == "removed":
                # A removed route comes back as a new one: its old confirmation may
                # describe a station that no longer exists, so the path is asked again.
                self._clear_route_checks(rid)
                route = Route(
                    route_id=rid,
                    company_id=company_id,
                    vehicle_type=vtype,
                    station_ids=list(sids),
                    created_at=game_date,
                )
                self._routes[rid] = route
                logger.info("Route %s created: stations %s", rid, list(sids))

            route.vehicle_ids = [v.id for v in vlist]
            route.vehicle_count = len(vlist)
            route.total_profit_this_year = sum(v.profit_this_year for v in vlist)
            route.total_profit_last_year = sum(v.profit_last_year for v in vlist)
            route.vehicles_without_path = [v for v in route.vehicles_without_path if v in route.vehicle_ids]
            self._update_unknown_paths(route)
            if not route.first_vehicle_at:
                route.first_vehicle_at = game_date
            route.refresh_status()

        for rid, route in self._routes.items():
            if rid in active_route_ids:
                continue
            if route.vehicle_ids:
                self.connection_generation += 1
            self._clear_route_checks(rid)
            if route.status == "removed" or not all(sid in stations for sid in route.station_ids):
                route.status = "removed"
            route.vehicle_ids = []
            route.vehicle_count = 0
            route.total_profit_this_year = 0
            route.total_profit_last_year = 0
            route.vehicles_without_path = []
            route.vehicles_with_unknown_path = []
            route.refresh_status()

        return [r for r in self._routes.values() if r.status != "removed"]

    def vehicles_to_check(self, route: Route) -> list[int]:
        """Vehicles without a current successful walk to their first ordered station."""
        passed = self._vehicles_with_path.get(route.route_id, set())
        return [vid for vid in route.vehicle_ids if vid not in passed]

    def invalidate_connections(self, route_id: str | None = None) -> None:
        """Discard stale connectivity evidence without asserting a disconnection."""
        self.connection_generation += 1
        for route in self._routes.values():
            if route.status == "removed" or route.vehicle_type == "aircraft":
                continue
            if route_id is not None and route.route_id != route_id:
                continue
            route.track_confirmed_at = 0
            route.connection_checked_at = 0
            route.vehicles_without_path = []
            self._clear_route_checks(route.route_id)
            self._update_unknown_paths(route)
            route.refresh_status()

    def expire_connections(self, game_date: int) -> None:
        """Expire dormant routes; live routes recompute their per-probe evidence."""
        for route in list(self._routes.values()):
            if (not route.vehicle_ids and route.track_confirmed_at
                    and game_date - route.connection_checked_at >= self.CONNECTION_CACHE_DAYS):
                self.invalidate_connections(route.route_id)

    def _clear_route_checks(self, route_id: str) -> None:
        """Forget both positive vehicle evidence and outstanding retry schedules."""
        self._vehicles_with_path.pop(route_id, None)
        self._connection_checks = {
            key: check for key, check in self._connection_checks.items() if key[0] != route_id
        }

    def retain_connection_checks(self, keys: set[CheckKey]) -> None:
        """Remove probes for vehicles or itinerary legs that no longer exist."""
        self._connection_checks = {key: check for key, check in self._connection_checks.items() if key in keys}

    def next_connection_check(self, keys: set[CheckKey], game_date: int) -> CheckKey | None:
        """Choose an oldest due probe, rotating among routes to avoid starvation."""
        due: dict[str, list[tuple[int, CheckKey]]] = {}
        for key in keys:
            check = self._connection_checks.get(key)
            if check is None or game_date >= check.next_check_at:
                due.setdefault(key[0], []).append((check.checked_at if check else -1, key))
        if not due:
            return None
        route_ids = sorted(due)
        route_id = next((rid for rid in route_ids if rid > self._last_checked_route), route_ids[0])
        self._last_checked_route = route_id
        return min(due[route_id])[1]

    def record_connection_check(self, key: CheckKey, answer: bool | None, game_date: int) -> None:
        """Back off unsuccessful probes; cache successful ones for a bounded time."""
        previous = self._connection_checks.get(key)
        failures = min((previous.failures if previous else 0) + 1, 4) if answer is not True else 0
        delay = (min(self.RETRY_INITIAL_DAYS * 2 ** (failures - 1), self.RETRY_MAX_DAYS)
                 if failures else self.CONNECTION_CACHE_DAYS)
        self._connection_checks[key] = ConnectionCheck(answer, game_date, game_date + delay, failures)

    def connection_check_answer(self, key: CheckKey, game_date: int) -> bool | None:
        """Expired or absent evidence stays unknown until its queued probe runs."""
        check = self._connection_checks.get(key)
        return check.answer if check is not None and game_date < check.next_check_at else None

    def connection_checks_date(self, keys: list[CheckKey], game_date: int) -> int:
        """Oldest observation supporting a combined connection claim."""
        return min((self._connection_checks[key].checked_at for key in keys if key in self._connection_checks),
                   default=game_date)

    def _update_unknown_paths(self, route: Route) -> None:
        passed = self._vehicles_with_path.get(route.route_id, set())
        route.vehicles_with_unknown_path = [
            vid for vid in route.vehicle_ids
            if vid not in passed and vid not in route.vehicles_without_path
        ]

    def record_vehicle_paths(
        self, route_id: str, with_path: list[int], without_path: list[int], game_date: int,
        unknown: list[int] | None = None,
    ) -> None:
        """Store which vehicles can reach their first ordered station from their own tile.

        Unmentioned vehicles keep their entries; explicitly unknown answers revoke them."""
        route = self._routes.get(route_id)
        if route is None or route.status == "removed":
            return
        passed = self._vehicles_with_path.setdefault(route_id, set())
        passed.difference_update(without_path + (unknown or []))
        passed.update(with_path)
        answered = set(with_path) | set(without_path) | set(unknown or [])
        kept = [v for v in route.vehicles_without_path if v not in answered and v in route.vehicle_ids]
        route.vehicles_without_path = sorted(set(without_path) | set(kept))
        self._update_unknown_paths(route)
        route.refresh_status()

    def record_connection(self, route_id: str, connected: bool | None, game_date: int) -> None:
        """Store the game's answer about the path between the route's stations."""
        route = self._routes.get(route_id)
        if route is None or route.status == "removed":
            return
        route.connection_checked_at = game_date if connected is not None else 0
        if connected is not True:
            route.track_confirmed_at = 0
        if connected and not route.track_confirmed_at:
            route.track_confirmed_at = game_date
            logger.info("Route %s: path confirmed", route_id)
        route.refresh_status()

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
            self._handle_connect_rail(params, result, stations, game_date)
        elif action_type == "build_rail_depot":
            self._handle_depot(params, stations)
        elif action_type in ("build_train", "buy_vehicle"):
            self._handle_vehicle_buy(params, result)

    def _handle_connect_rail(
        self,
        params: dict[str, Any],
        result: dict[str, Any],
        stations: dict[int, Station],
        game_date: int,
    ) -> None:
        from_x = params.get("from_x", 0)
        from_y = params.get("from_y", 0)
        to_x = params.get("to_x", 0)
        to_y = params.get("to_y", 0)

        path_tiles = _extract_path_tiles(result)

        src_sid = _find_station_near(from_x, from_y, stations)
        dst_sid = _find_station_near(to_x, to_y, stations)
        if src_sid is None or dst_sid is None:
            return

        for route in self._routes.values():
            if route.status != "planned":
                continue
            route_sids = set(route.station_ids)
            if {src_sid, dst_sid} == route_sids:
                route.track_confirmed_at = game_date
                route.path_tiles = path_tiles
                route.refresh_status()
                logger.info("Route %s: track confirmed (%d path tiles)", route.route_id, len(path_tiles))
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
                path_tiles=path_tiles,
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
                map_width = self._map_width
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


def _extract_path_tiles(result: dict[str, Any], map_width: int = 256) -> list[int]:
    """Convert connect_rail result path [{x, y, dir}, ...] to tile integers."""
    path = result.get("path", [])
    return [pt.get("y", 0) * map_width + pt.get("x", 0) for pt in path]


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
