"""Route planner: compute cargo chain routes, town routes, and existing route
summaries from typed game entities.

Used by both the live agent observation pipeline (from WorldState) and the
offline analysis reports (from deserialized StateSnapshot). All methods return
plain dicts suitable for JSON serialization.
"""

import logging
from typing import Any, Sequence

from nttd.schemas.industry import Industry
from nttd.schemas.route import Route
from nttd.schemas.station import Station
from nttd.schemas.town import Town

logger = logging.getLogger(__name__)

# Transport mode suitability thresholds (Manhattan distance in tiles)
ROAD_MAX_DISTANCE = 80
AIR_MIN_DISTANCE = 100

# Maps agent_type -> set of transport mode strings that agent operates
AGENT_MODE_FILTER: dict[str, set[str]] = {
    "road": {"road"},
    "rail": {"rail"},
    "air": {"air"},
    "water": {"water"},
    "general": {"road", "rail", "water", "air"},
}


def manhattan(x1: int, y1: int, x2: int, y2: int) -> int:
    """Manhattan distance between two map coordinates."""
    return abs(x1 - x2) + abs(y1 - y2)


def classify_transport_modes(
    distance: int,
    has_water_src: bool,
    has_water_dst: bool,
    cargo: str,
) -> list[str]:
    """Determine suitable transport modes for a route.

    Args:
        distance: Manhattan distance in tiles.
        has_water_src: Whether source endpoint has water access.
        has_water_dst: Whether destination endpoint has water access.
        cargo: Cargo label (e.g. "COAL", "PASS").
    """
    modes: list[str] = []
    if distance <= ROAD_MAX_DISTANCE:
        modes.append("road")
    modes.append("rail")
    if has_water_src and has_water_dst:
        modes.append("water")
    if distance >= AIR_MIN_DISTANCE and cargo in ("PASS", "MAIL", "VALU"):
        modes.append("air")
    return modes


def _station_nearby(
    station_locs: set[tuple[int, int]],
    x: int,
    y: int,
    radius: int = 10,
) -> bool:
    """Check if any station is within Manhattan radius of (x, y)."""
    for sx, sy in station_locs:
        if abs(sx - x) + abs(sy - y) <= radius:
            return True
    return False


def _dock_nearby(
    dock_locs: set[tuple[int, int]],
    x: int,
    y: int,
    radius: int = 15,
) -> bool:
    """Check if any dock station is within Manhattan radius of (x, y)."""
    for dx, dy in dock_locs:
        if abs(dx - x) + abs(dy - y) <= radius:
            return True
    return False


class RoutePlanner:
    """Compute route planning data from typed game entities.

    Accepts pydantic model sequences from either WorldState (live) or
    StateSnapshot (offline analysis). All output methods return plain
    dicts for JSON serialization.
    """

    def __init__(
        self,
        industries: Sequence[Industry],
        towns: Sequence[Town],
        stations: Sequence[Station],
        routes: Sequence[Route],
    ) -> None:
        self._industries = industries
        self._towns = towns
        self._stations = stations
        self._routes = routes
        self._station_locs = {(s.x, s.y) for s in stations}
        self._dock_locs = {(s.x, s.y) for s in stations if s.has_dock}

    def cargo_routes(self) -> list[dict[str, Any]]:
        """All possible cargo chain routes (producer -> consumer).

        Each route pairs an industry that produces a cargo with one that
        accepts it. Sorted by distance ascending.
        """
        producers: dict[str, list[Industry]] = {}
        consumers: dict[str, list[Industry]] = {}

        for ind in self._industries:
            for p in ind.production:
                if p.cargo_label:
                    producers.setdefault(p.cargo_label, []).append(ind)
            for a in ind.accepted:
                if a.cargo_label:
                    consumers.setdefault(a.cargo_label, []).append(ind)

        result: list[dict[str, Any]] = []
        for cargo_label, srcs in producers.items():
            dsts = consumers.get(cargo_label, [])
            for src in srcs:
                for dst in dsts:
                    if src.id == dst.id:
                        continue
                    dist = manhattan(src.x, src.y, dst.x, dst.y)
                    water_src = _dock_nearby(self._dock_locs, src.x, src.y)
                    water_dst = _dock_nearby(self._dock_locs, dst.x, dst.y)
                    served = (
                        _station_nearby(self._station_locs, src.x, src.y)
                        and _station_nearby(self._station_locs, dst.x, dst.y)
                    )
                    monthly = 0
                    for p in src.production:
                        if p.cargo_label == cargo_label:
                            monthly = p.last_month
                            break

                    result.append({
                        "source_id": src.id,
                        "source_name": src.name,
                        "source_type": src.type_name,
                        "source_x": src.x,
                        "source_y": src.y,
                        "dest_id": dst.id,
                        "dest_name": dst.name,
                        "dest_type": dst.type_name,
                        "dest_x": dst.x,
                        "dest_y": dst.y,
                        "cargo": cargo_label,
                        "distance": dist,
                        "monthly_production": monthly,
                        "served": served,
                        "transport_modes": classify_transport_modes(
                            dist, water_src, water_dst, cargo_label,
                        ),
                    })

        result.sort(key=lambda r: r["distance"])
        return result

    def town_routes(self) -> list[dict[str, Any]]:
        """All town-to-town passenger routes ranked by demand score.

        Demand score = (pop_a * pop_b) / max(distance, 1). Higher is better.
        """
        towns = list(self._towns)
        result: list[dict[str, Any]] = []
        for i, ta in enumerate(towns):
            for tb in towns[i + 1:]:
                dist = manhattan(ta.x, ta.y, tb.x, tb.y)
                demand = (ta.population * tb.population) // max(dist, 1)
                served = (
                    _station_nearby(self._station_locs, ta.x, ta.y)
                    and _station_nearby(self._station_locs, tb.x, tb.y)
                )
                water_a = _dock_nearby(self._dock_locs, ta.x, ta.y)
                water_b = _dock_nearby(self._dock_locs, tb.x, tb.y)
                result.append({
                    "town_a_id": ta.id,
                    "town_a_name": ta.name,
                    "town_a_pop": ta.population,
                    "town_a_x": ta.x,
                    "town_a_y": ta.y,
                    "town_b_id": tb.id,
                    "town_b_name": tb.name,
                    "town_b_pop": tb.population,
                    "town_b_x": tb.x,
                    "town_b_y": tb.y,
                    "distance": dist,
                    "demand_score": demand,
                    "served": served,
                    "transport_modes": classify_transport_modes(
                        dist, water_a, water_b, "PASS",
                    ),
                })

        result.sort(key=lambda r: r["demand_score"], reverse=True)
        return result

    def existing_routes_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Summarize active routes for a company.

        Enriches Route objects with station names for readability.
        """
        station_names: dict[int, str] = {s.id: s.name for s in self._stations}
        result: list[dict[str, Any]] = []
        for r in self._routes:
            if r.company_id != company_id:
                continue
            result.append({
                "route_id": r.route_id,
                "vehicle_type": r.vehicle_type,
                "station_ids": r.station_ids,
                "station_names": [station_names.get(sid, f"#{sid}") for sid in r.station_ids],
                "vehicle_count": r.vehicle_count,
                "profit_this_year": r.total_profit_this_year,
                "profit_last_year": r.total_profit_last_year,
            })
        return result

    def for_agent(
        self,
        company_id: int,
        agent_type: str = "general",
        compact: bool = False,
    ) -> dict[str, Any]:
        """Complete route planning observation filtered for an agent type.

        Args:
            company_id: The agent's company.
            agent_type: Transport mode filter (road/rail/air/water/general).
            compact: If True, return shorter field names, fewer items, and
                drop coordinates to minimize token usage.
        """
        allowed_modes = AGENT_MODE_FILTER.get(agent_type, AGENT_MODE_FILTER["general"])

        cargo = [
            r for r in self.cargo_routes()
            if allowed_modes & set(r["transport_modes"])
        ]
        towns = [
            r for r in self.town_routes()
            if allowed_modes & set(r["transport_modes"])
        ]
        existing = self.existing_routes_for_company(company_id)
        if agent_type != "general":
            vtype_map = {"road": "road", "rail": "train", "air": "aircraft", "water": "ship"}
            vtype = vtype_map.get(agent_type)
            if vtype:
                existing = [r for r in existing if r["vehicle_type"] == vtype]

        unserved_cargo = [r for r in cargo if not r["served"]]
        unserved_towns = [r for r in towns if not r["served"]]

        if compact:
            return self._compact_output(
                cargo, towns, unserved_cargo, unserved_towns, existing,
            )

        return {
            "existing_routes": existing,
            "top_unserved_cargo": unserved_cargo[:5],
            "top_unserved_towns": unserved_towns[:5],
            "summary": {
                "total_cargo_routes": len(cargo),
                "unserved_cargo_routes": len(unserved_cargo),
                "total_town_routes": len(towns),
                "unserved_town_routes": len(unserved_towns),
                "active_routes": len(existing),
            },
        }

    def _compact_output(
        self,
        cargo: list[dict[str, Any]],
        towns: list[dict[str, Any]],
        unserved_cargo: list[dict[str, Any]],
        unserved_towns: list[dict[str, Any]],
        existing: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a compact route planning dict for token-efficient observations."""
        return {
            "active": [
                {
                    "stations": r["station_names"],
                    "vehicles": r["vehicle_count"],
                    "profit": r["profit_this_year"],
                }
                for r in existing
            ],
            "top_cargo": [
                {
                    "src": r["source_name"],
                    "dst": r["dest_name"],
                    "cargo": r["cargo"],
                    "dist": r["distance"],
                    "prod": r["monthly_production"],
                    "src_x": r["source_x"],
                    "src_y": r["source_y"],
                    "dst_x": r["dest_x"],
                    "dst_y": r["dest_y"],
                }
                for r in unserved_cargo[:5]
            ],
            "top_towns": [
                {
                    "a": r["town_a_name"],
                    "b": r["town_b_name"],
                    "dist": r["distance"],
                    "demand": r["demand_score"],
                    "a_x": r["town_a_x"],
                    "a_y": r["town_a_y"],
                    "b_x": r["town_b_x"],
                    "b_y": r["town_b_y"],
                }
                for r in unserved_towns[:5]
            ],
            "totals": {
                "cargo_routes": len(cargo),
                "town_routes": len(towns),
                "unserved": len(unserved_cargo) + len(unserved_towns),
            },
        }
