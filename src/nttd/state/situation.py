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

Live only. The ``analysis`` package computes richer versions of several of these, but it
reads finalised parquet from a session directory and ``snapshots.parquet`` does not exist
until a run ends, so none of it can answer a question during play.
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


class Situation:
    """One company's position, as facts an agent can act on."""

    def __init__(
        self,
        company: Company | None,
        stations: list[Station],
        vehicles: list[Vehicle],
        routes: list[Route],
    ) -> None:
        self._company = company
        self._stations = stations
        self._vehicles = vehicles
        self._routes = routes

    def report(self) -> dict[str, Any]:
        """The whole position: money, what is built, what earns, and what is wrong."""
        return {
            "money": self._money(),
            "built": self._built(),
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
            "vehicles": route.vehicle_count,
            "profit_this_year": route.total_profit_this_year,
            "working": not missing,
            "missing": missing,
        }

    def _problems(self) -> list[dict[str, str]]:
        """What is wrong, in the order worth fixing.

        Each carries what to do about it. A problem an agent cannot act on is an
        observation, and it belongs in the report rather than here.
        """
        found: list[dict[str, str]] = []

        for route in self._routes:
            health = self._route_health(route)
            if not health["working"]:
                found.append({
                    "problem": f"route {route.route_id} is unfinished",
                    "detail": f"it still needs {', '.join(health['missing'])}",
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
                    "detail": "it has no vehicles calling at it",
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
