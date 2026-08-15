import logging
import uuid
from typing import Any

from nttd.schemas.cargo_flow import CargoFlow
from nttd.schemas.company import Company
from nttd.schemas.game import GameState, RuntimeMode
from nttd.schemas.industry import Industry, IndustryAcceptance, IndustryProduction
from nttd.schemas.infrastructure import InfrastructureCosts
from nttd.schemas.route import Route
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.station import CargoAcceptance, CargoWaiting, Station
from nttd.schemas.subsidy import Subsidy
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Order, Vehicle
from nttd.state.route_registry import RouteRegistry
from nttd.utils.game_text import sanitise

logger = logging.getLogger(__name__)


class WorldState:
    """In-memory canonical world state. Bridge writes, API reads."""

    def __init__(self) -> None:
        self.game: GameState = GameState()
        self.companies: dict[int, Company] = {}
        self.towns: dict[int, Town] = {}
        self.industries: dict[int, Industry] = {}
        self.stations: dict[int, Station] = {}
        self.vehicles: dict[int, Vehicle] = {}
        self.subsidies: list[Subsidy] = []
        self.infrastructure: dict[int, InfrastructureCosts] = {}
        self.cargo_flows: list[CargoFlow] = []
        self.route_registry: RouteRegistry = RouteRegistry()

    def snapshot(self) -> StateSnapshot:
        self.game.snapshot_id = uuid.uuid4().hex[:12]
        return StateSnapshot(
            game=self.game.model_copy(),
            companies=list(self.companies.values()),
            towns=list(self.towns.values()),
            industries=list(self.industries.values()),
            stations=list(self.stations.values()),
            vehicles=list(self.vehicles.values()),
            routes=self._derive_routes(),
            subsidies=list(self.subsidies),
            infrastructure=list(self.infrastructure.values()),
            cargo_flows=list(self.cargo_flows),
        )

    def set_mode(self, mode: RuntimeMode) -> None:
        self.game.mode = mode

    def set_paused(self, paused: bool) -> None:
        self.game.paused = paused

    def set_speed(self, speed: int) -> None:
        self.game.speed = speed

    def update_company(self, company: Company) -> None:
        self.companies[company.id] = company

    def update_town(self, town: Town) -> None:
        self.towns[town.id] = town

    def update_industry(self, industry: Industry) -> None:
        self.industries[industry.id] = industry

    def update_station(self, station: Station) -> None:
        self.stations[station.id] = station

    def update_vehicle(self, vehicle: Vehicle) -> None:
        self.vehicles[vehicle.id] = vehicle

    def apply_gs_towns(self, results: list[dict[str, Any]]) -> None:
        """Populate towns dict from GS get_towns result."""
        seen = set()
        for r in results:
            tid = r["id"]
            seen.add(tid)
            self.towns[tid] = Town(
                id=tid,
                name=sanitise(r.get("name")),
                population=r.get("population", 0),
                houses=r.get("houses", 0),
                x=r.get("x", 0),
                y=r.get("y", 0),
                is_city=r.get("is_city", False),
                growth_rate=r.get("growth_rate", 0),
            )
        # Remove towns that no longer exist
        for tid in list(self.towns.keys()):
            if tid not in seen:
                del self.towns[tid]
        logger.debug("WorldState: refreshed %d towns", len(self.towns))

    def apply_gs_industries(self, results: list[dict[str, Any]]) -> None:
        """Populate industries dict from GS get_industries result."""
        seen = set()
        for r in results:
            iid = r["id"]
            seen.add(iid)
            production = [
                IndustryProduction(
                    cargo_id=p.get("cargo_id", 0),
                    cargo_label=p.get("cargo_label", ""),
                    last_month=p.get("last_month", 0),
                    transported=p.get("transported", 0),
                )
                for p in r.get("production", [])
            ]
            accepted = [
                IndustryAcceptance(
                    cargo_id=a.get("cargo_id", 0),
                    cargo_label=a.get("cargo_label", ""),
                )
                for a in r.get("accepted", [])
            ]
            self.industries[iid] = Industry(
                id=iid,
                name=sanitise(r.get("name")),
                type_id=r.get("type_id", 0),
                type_name=sanitise(r.get("type_name")),
                x=r.get("x", 0),
                y=r.get("y", 0),
                is_raw=r.get("is_raw", False),
                is_processing=r.get("is_processing", False),
                production=production,
                accepted=accepted,
            )
        for iid in list(self.industries.keys()):
            if iid not in seen:
                del self.industries[iid]
        logger.debug("WorldState: refreshed %d industries", len(self.industries))

    def apply_gs_stations(self, company_id: int, results: list[dict[str, Any]]) -> None:
        """Populate stations dict from GS get_stations result."""
        seen = set()
        for r in results:
            sid = r["id"]
            seen.add(sid)
            cargo_waiting = [
                CargoWaiting(
                    cargo_id=c.get("cargo_id", 0),
                    cargo_label=c.get("cargo_label", ""),
                    waiting=c.get("waiting", 0),
                )
                for c in r.get("cargo_waiting", [])
            ]
            cargo_acceptance = [
                CargoAcceptance(
                    cargo_id=c.get("cargo_id", 0),
                    cargo_label=c.get("cargo_label", ""),
                    accepts=c.get("accepts", False),
                    produces=c.get("produces", False),
                    supply=c.get("supply", 0),
                    rated=c.get("rated", False),
                )
                for c in r.get("cargo_acceptance", [])
            ]
            self.stations[sid] = Station(
                id=sid,
                name=sanitise(r.get("name")),
                company_id=company_id,
                x=r.get("x", 0),
                y=r.get("y", 0),
                has_rail=r.get("has_rail", False),
                has_truck=r.get("has_truck", False),
                has_bus=r.get("has_bus", False),
                has_airport=r.get("has_airport", False),
                has_dock=r.get("has_dock", False),
                cargo_waiting=cargo_waiting,
                cargo_acceptance=cargo_acceptance,
            )
        logger.debug("WorldState: refreshed %d stations for company %d", len(seen), company_id)

    def apply_gs_vehicles(self, company_id: int, results: list[dict[str, Any]]) -> None:
        """Populate vehicles dict from GS get_vehicles result."""
        seen = set()
        for r in results:
            vid = r["id"]
            seen.add(vid)
            orders = [
                Order(
                    index=o.get("index", 0),
                    destination=o.get("destination", 0),
                    flags=o.get("flags", 0),
                    is_goto_station=o.get("is_goto_station", False),
                    is_goto_depot=o.get("is_goto_depot", False),
                    is_goto_waypoint=o.get("is_goto_waypoint", False),
                )
                for o in r.get("orders", [])
            ]
            self.vehicles[vid] = Vehicle(
                id=vid,
                type=r.get("type", "train"),
                company_id=company_id,
                name=sanitise(r.get("name")),
                engine_id=r.get("engine_id", 0),
                x=r.get("x", 0),
                y=r.get("y", 0),
                capacity=r.get("capacity", 0),
                profit_this_year=r.get("profit_this_year", 0),
                profit_last_year=r.get("profit_last_year", 0),
                age=r.get("age", 0),
                max_age=r.get("max_age", 0),
                current_speed=r.get("current_speed", 0),
                state=r.get("state", 0),
                running=not r.get("in_depot", False),
                in_depot=r.get("in_depot", False),
                order_count=r.get("order_count", 0),
                orders=orders,
            )
        # Remove stale vehicles no longer returned by GS for this company
        stale = [vid for vid, v in self.vehicles.items()
                 if v.company_id == company_id and vid not in seen]
        for vid in stale:
            del self.vehicles[vid]
        logger.debug("WorldState: refreshed %d vehicles for company %d (removed %d stale)",
                      len(seen), company_id, len(stale))

    def tile_to_station_id(self, tile: int) -> int | None:
        """Convert a tile index (from GSOrder.GetOrderDestination) to a station ID."""
        map_w = self.game.map_width or 256
        for sid, station in self.stations.items():
            if station.y * map_w + station.x == tile:
                return sid
        return None

    def _derive_routes(self) -> list[Route]:
        """Reconcile route registry and return all active routes with stable IDs."""
        return self.route_registry.reconcile(
            self.vehicles, self.stations, self.game.game_date,
            map_width=self.game.map_width or 256,
        )

    def apply_gs_companies(self, results: list[dict[str, Any]]) -> None:
        """Populate companies dict from GS get_companies result.

        Merges with existing entries so admin-port financial data (money/loan/income)
        written by the Bridge is preserved when GS doesn't include those fields.
        Companies absent from the GS result are marked inactive.
        """
        seen: set[int] = set()
        for r in results:
            cid = r.get("id")
            if cid is None:
                continue
            # Skip empty company slots (GS returns all 16 with money=-1 for unused)
            if r.get("money", -1) == -1 and r.get("name") is None:
                continue
            seen.add(cid)
            company = self.companies.get(cid)
            if company is None:
                company = Company(id=cid)
            company.name = sanitise(r.get("name", company.name))
            company.manager = r.get("manager", company.manager)
            company.color = r.get("color", company.color)
            company.is_ai = r.get("is_ai", company.is_ai)
            company.is_active = True
            # Financial fields. The GS emits "money" and "company_value"; the
            # admin port uses "balance" and "value", so both spellings are
            # accepted and whichever arrives wins.
            for field, keys in (
                ("money", ("money", "balance")),
                ("loan", ("loan",)),
                ("max_loan", ("max_loan",)),
                ("income", ("income",)),
                ("value", ("company_value", "value")),
                ("performance_rating", ("performance_rating",)),
                ("q0_income", ("q0_income",)),
                ("q0_expenses", ("q0_expenses",)),
                ("q0_cargo", ("q0_cargo",)),
                # The scored one. Absent from this list it kept the model default of 0, so
                # every result row reported no cargo however much the GameScript had sent.
                ("cargo_delivered_total", ("cargo_delivered_total",)),
            ):
                for key in keys:
                    if key in r and r[key] is not None:
                        setattr(company, field, r[key])
                        break
            self.companies[cid] = company
        for cid in list(self.companies.keys()):
            if cid not in seen:
                self.companies[cid].is_active = False
        logger.debug("WorldState: refreshed %d companies from GS", len(seen))

    def apply_gs_company_finance(self, company_id: int, result: dict[str, Any]) -> None:
        """Merge financial data from GS get_company_finance into an existing company entry.

        GS CmdGetCompanyFinance returns: balance, loan, q1_income, q1_value, q2_income, q2_value.
        We map these to Company fields, falling back to existing values when absent.
        """
        company = self.companies.get(company_id)
        if company is None:
            return

        def _int(val: Any, default: int) -> int:
            try:
                return int(val) if val is not None else default
            except (TypeError, ValueError):
                return default

        company.money = _int(result.get("balance"), company.money)
        company.loan = _int(result.get("loan"), company.loan)
        # GS returns quarterly income; use q1 as the current-period income
        company.income = _int(result.get("q1_income", result.get("income")), company.income)
        company.value = _int(result.get("q1_value", result.get("value")), company.value)

    def apply_gs_subsidies(self, results: list[dict[str, Any]]) -> None:
        """Populate subsidies list from GS get_subsidies result."""
        _type_map = {0: "industry", 1: "town"}
        self.subsidies = [
            Subsidy(
                id=r.get("id", 0),
                cargo_id=r.get("cargo_id", 0),
                cargo_label=r.get("cargo_label", ""),
                src_type=_type_map.get(r.get("src_type", -1), ""),
                src_id=r.get("src_id", 0),
                src_name=sanitise(r.get("src_name")),
                dst_type=_type_map.get(r.get("dst_type", -1), ""),
                dst_id=r.get("dst_id", 0),
                dst_name=sanitise(r.get("dst_name")),
                value=r.get("value", 0),
                remaining_years=r.get("remaining_years", 0),
            )
            for r in results
        ]
        logger.debug("WorldState: refreshed %d subsidies", len(self.subsidies))

    def apply_gs_infrastructure(self, company_id: int, result: dict[str, Any]) -> None:
        """Populate infrastructure costs from GS get_infrastructure_costs result."""
        self.infrastructure[company_id] = InfrastructureCosts(
            company_id=company_id,
            rail_pieces=result.get("rail_pieces", 0),
            road_pieces=result.get("road_pieces", 0),
            water_pieces=result.get("water_pieces", 0),
            station_pieces=result.get("station_pieces", 0),
            airport_pieces=result.get("airport_pieces", 0),
            rail_cost=result.get("rail_cost", 0),
            road_cost=result.get("road_cost", 0),
            water_cost=result.get("water_cost", 0),
            station_cost=result.get("station_cost", 0),
            airport_cost=result.get("airport_cost", 0),
        )
        logger.debug("WorldState: refreshed infrastructure for company %d", company_id)

    def apply_gs_cargo_flows(self, company_id: int, results: list[dict[str, Any]]) -> None:
        """Populate cargo flows from GS get_cargo_flows result.

        Replaces all flows for the given company (each read resets GS counters).
        """
        self.cargo_flows = [
            f for f in self.cargo_flows if f.company_id != company_id
        ]
        for r in results:
            self.cargo_flows.append(CargoFlow(
                company_id=company_id,
                cargo_id=r.get("cargo_id", 0),
                cargo_label=r.get("cargo_label", ""),
                entity_type=r.get("entity_type", ""),
                entity_id=r.get("entity_id", 0),
                entity_name=sanitise(r.get("entity_name")),
                direction=r.get("direction", ""),
                amount=r.get("amount", 0),
            ))
        logger.debug("WorldState: refreshed %d cargo flows for company %d",
                      len(results), company_id)
