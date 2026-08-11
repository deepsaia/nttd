"""What position a company is in, computed rather than described.

Every figure here is arithmetic over the world state. It exists because an agent that
derives its own numbers from a raw observation is spending a model call on counting, and
getting it wrong is a way for a good decision-maker to look bad. A benchmark measuring
business judgement should not also be measuring whether a model can add up.

So the split is: this reports the facts, and the agent decides what to do about them.

**The formulas match the ones the board scores.** Operating margin here is the same
expression as ``analysis.business_metrics``, deliberately. An agent judging itself by a
different yardstick than its scorer optimises the wrong thing, which is a subtle way for
a benchmark to be unfair.

In the loop, rather than after it. The ``analysis`` package computes richer versions of
several of these and does work on a running session, because nttd writes a snapshot
fragment per step and the read path falls back to fragments until they are merged. What it
cannot be is part of a decision: it re-reads a session's whole history from disk to build
a report, which is the right shape for ``nttd analyze`` and ``nttd monitor`` and the wrong
one for a question asked between two steps.
"""

from __future__ import annotations

from typing import Any

from nttd.schemas.company import Company
from nttd.schemas.route import Route
from nttd.schemas.station import Station
from nttd.schemas.vehicle import Vehicle

# A vehicle younger than this has not had time to earn, so a negative figure says
# nothing yet. Judging one too early is how a policy talks itself into selling a route
# that was about to work.
_SETTLING_DAYS = 400

# Cargo sitting at a station in these quantities means the route cannot clear what it
# collects. Below it, waiting cargo is just the gap between vehicle visits.
_PILING_UP = 100


def _serves(station: Station) -> list[str]:
    """Which transports call at a station.

    A list rather than one label: a station can take a bus stop and a dock, and telling an
    agent only the first would have it rebuild what it already owns.
    """
    kinds = []
    for flag, label in (
        (station.has_rail, "rail"),
        (station.has_bus, "bus"),
        (station.has_truck, "truck"),
        (station.has_dock, "dock"),
        (station.has_airport, "airport"),
    ):
        if flag:
            kinds.append(label)
    return kinds


class Situation:
    """One company's position, as facts an agent can act on."""

    def __init__(
        self,
        company: Company | None,
        stations: list[Station],
        vehicles: list[Vehicle],
        routes: list[Route],
        map_width: int = 0,
    ) -> None:
        self._company = company
        self._stations = stations
        self._vehicles = vehicles
        self._routes = routes
        self._map_width = map_width

    def report(self) -> dict[str, Any]:
        """The whole position: money, what is built and where, what earns, what is wrong."""
        return {
            "money": self._money(),
            "built": self._built(),
            "stations": [self._station_detail(s) for s in self._stations],
            "vehicles": [self._vehicle_detail(v) for v in self._vehicles],
            "earning": self._earning(),
            "routes": [self._route_health(r) for r in self._routes],
            "problems": self._problems(),
        }

    # ------------------------------------------------------------------

    def _money(self) -> dict[str, Any]:
        c = self._company
        if c is None:
            return {"balance": 0, "loan": 0, "headroom": 0, "max_loan": 0}
        return {
            "balance": c.money,
            "loan": c.loan,
            # What could still be borrowed. More useful than the loan alone, which
            # answers a question nobody asks.
            "headroom": max(0, c.max_loan - c.loan),
            "max_loan": c.max_loan,
            "company_value": c.value,
        }

    def _built(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for v in self._vehicles:
            by_type[v.type] = by_type.get(v.type, 0) + 1
        return {
            "stations": len(self._stations),
            "vehicles": len(self._vehicles),
            "vehicles_by_type": by_type,
            "routes": len(self._routes),
        }

    def _station_detail(self, station: Station) -> dict[str, Any]:
        """One station, including where it is.

        The coordinates are the point of this. Counts alone told an agent it owned two
        stations and gave it no way to find them, and a station it cannot locate is a
        station it cannot connect: a rail run built two at its first step and then spent 26
        of its remaining 27 steps hunting for them, submitting nothing. Its own words were
        "the situation only tells me they exist by name but not coordinates".

        Both forms are given because both are used. Actions take ``tile``, and the finders
        and anything reasoning about distance work in x and y.
        """
        return {
            "station_id": station.id,
            "name": station.name,
            "tile": self._tile(station.x, station.y),
            "x": station.x,
            "y": station.y,
            "serves": _serves(station),
            "cargo_waiting": [
                {"cargo": c.cargo_label, "waiting": c.waiting}
                for c in station.cargo_waiting
                if c.waiting
            ],
        }

    def _vehicle_detail(self, vehicle: Vehicle) -> dict[str, Any]:
        """One vehicle, including where it currently is."""
        return {
            "vehicle_id": vehicle.id,
            "name": vehicle.name,
            "type": vehicle.type,
            "tile": self._tile(vehicle.x, vehicle.y),
            "x": vehicle.x,
            "y": vehicle.y,
            "orders": vehicle.order_count,
            "profit_this_year": vehicle.profit_this_year,
            "age_days": vehicle.age,
        }

    def _tile(self, x: int, y: int) -> int | None:
        """The tile index for a coordinate pair, which is what actions take.

        None rather than a wrong number when the map width is unknown. A tile index
        computed against the wrong width points somewhere real and somewhere else, which
        is worse than admitting the answer is unavailable.
        """
        if not self._map_width:
            return None
        return y * self._map_width + x

    def _earning(self) -> dict[str, Any]:
        c = self._company
        income = c.income if c else 0
        profits = [v.profit_this_year for v in self._vehicles]
        return {
            "income": income,
            "profit_last_year": c.profit_last_year if c else 0,
            "vehicles_earning": sum(1 for p in profits if p > 0),
            "vehicles_losing": sum(1 for p in profits if p < 0),
            "fleet_profit_this_year": sum(profits),
        }

    def _route_health(self, route: Route) -> dict[str, Any]:
        """One route, and whether it is actually working.

        A route is only working when every part is present. Stations without track,
        track without a depot, a depot without a vehicle: each is a state that looks
        like progress and earns nothing, and each is a state a run can sit in for
        dozens of steps without noticing.
        """
        missing = []
        if len(route.station_ids) < 2:
            missing.append("a second station")
        if not route.track_confirmed_at:
            missing.append("a connection between the stations")
        if not route.depot_tile:
            missing.append("a depot")
        if not route.vehicle_count:
            missing.append("a vehicle")
        return {
            "route_id": route.route_id,
            "vehicle_type": route.vehicle_type,
            "stations": route.station_ids,
            # The tiles of this route's own stations, so connecting them does not need a
            # lookup against the station list first. This is the question every unfinished
            # route poses, and the answer was previously nowhere.
            "station_tiles": self._tiles_of(route.station_ids),
            "depot_tile": route.depot_tile or None,
            "vehicles": route.vehicle_count,
            "profit_this_year": route.total_profit_this_year,
            "working": not missing,
            "missing": missing,
        }

    def _tiles_of(self, station_ids: list[int]) -> list[int | None]:
        by_id = {station.id: station for station in self._stations}
        return [
            self._tile(by_id[sid].x, by_id[sid].y)
            for sid in station_ids
            if sid in by_id
        ]

    def _problems(self) -> list[dict[str, str]]:
        """What is wrong, in the order worth fixing.

        Each carries what to do about it. A problem an agent cannot act on is an
        observation, and it belongs in the report rather than here.
        """
        found: list[dict[str, str]] = []

        for route in self._routes:
            health = self._route_health(route)
            if not health["working"]:
                tiles = ", ".join(str(t) for t in health["station_tiles"] if t)
                found.append({
                    "problem": f"route {route.route_id} is unfinished",
                    "detail": (
                        f"it still needs {', '.join(health['missing'])}"
                        + (f"; its stations are at tiles {tiles}" if tiles else "")
                    ),
                    "why_it_matters": (
                        "an unfinished route earns nothing while having already cost "
                        "what it cost, so finishing it beats starting another"
                    ),
                })

        served = {sid for r in self._routes for sid in r.station_ids}
        for station in self._stations:
            if station.id not in served:
                found.append({
                    "problem": f"station {station.name or station.id} serves no route",
                    "detail": (
                        f"it has no vehicles calling at it, and it is at tile "
                        f"{self._tile(station.x, station.y)} ({station.x}, {station.y})"
                    ),
                    "why_it_matters": "infrastructure without vehicles earns nothing",
                })
            piled = [c for c in station.cargo_waiting if c.waiting >= _PILING_UP]
            if piled:
                labels = ", ".join(f"{c.waiting} {c.cargo_label}" for c in piled)
                found.append({
                    "problem": f"cargo is piling up at {station.name or station.id}",
                    "detail": labels,
                    "why_it_matters": (
                        "the route collects faster than it clears, so another vehicle "
                        "on this route earns more than a new route would"
                    ),
                })

        for vehicle in self._vehicles:
            if not vehicle.order_count:
                found.append({
                    "problem": f"vehicle {vehicle.name or vehicle.id} has no orders",
                    "detail": "it will sit where it is",
                    "why_it_matters": "a vehicle without orders costs running expenses and carries nothing",
                })
            elif vehicle.profit_this_year < 0 and vehicle.age > _SETTLING_DAYS:
                found.append({
                    "problem": f"vehicle {vehicle.name or vehicle.id} is losing money",
                    "detail": f"{vehicle.profit_this_year} this year, age {vehicle.age} days",
                    "why_it_matters": (
                        "old enough that this is the route rather than settling in"
                    ),
                })

        return found
