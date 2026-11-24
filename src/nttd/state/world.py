import logging
import uuid
from typing import Any

from nttd.schemas.cargo_flow import CargoFlow
from nttd.schemas.company import Company
from nttd.schemas.game import GameState, RuntimeMode
from nttd.schemas.industry import Industry, IndustryAcceptance, IndustryProduction, NearbyStation
from nttd.schemas.infrastructure import InfrastructureCosts
from nttd.schemas.route import Route
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.station import CargoAcceptance, CargoWaiting, Station
from nttd.schemas.subsidy import Subsidy
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Order, Vehicle
from nttd.state.finance import RevenueLedger
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
        self._revenue_ledgers: dict[int, RevenueLedger] = {}

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
                houses=r.get("houses"),
                x=r.get("x", 0),
                y=r.get("y", 0),
                is_city=r.get("is_city"),
                growth_rate=r.get("growth_rate"),
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
            nearby = r.get("nearby_stations", r.get("served_by"))
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
                produces_cargo=r.get("produces_cargo"),
                accepts_cargo=r.get("accepts_cargo"),
                nearby_stations=[
                    NearbyStation(**{**station, "name": sanitise(station.get("name"))})
                    for station in nearby
                ] if nearby is not None else None,
                nearby_stations_company_id=r.get("nearby_stations_company_id"),
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
                    supply_is_estimate=c.get("supply_is_estimate", True),
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
        # A complete per-company listing replaces that company's station set.
        # Keeping deleted stations here also left ghost route endpoints behind.
        for sid, station in list(self.stations.items()):
            if station.company_id == company_id and sid not in seen:
                del self.stations[sid]
        logger.debug("WorldState: refreshed %d stations for company %d", len(seen), company_id)

    def apply_gs_vehicles(self, company_id: int, results: list[dict[str, Any]]) -> None:
        """Populate vehicles dict from GS get_vehicles result."""
        seen = set()
        for r in results:
            vid = r["id"]
            seen.add(vid)
            orders = [
                Order(
                    index=o.get("index", order_index),
                    destination=o.get("destination", 0),
                    flags=o.get("flags", 0),
                    is_goto_station=o.get("is_goto_station", False),
                    is_goto_depot=o.get("is_goto_depot", False),
                    is_goto_waypoint=o.get("is_goto_waypoint", False),
                    is_conditional=o.get("is_conditional", False),
                )
                for order_index, o in enumerate(r.get("orders", []))
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
                state=r.get("state"),
                # OpenTTD VS_RUNNING is 0. A stopped vehicle outside a depot is
                # still stopped; depot membership is not a substitute for state.
                running=r.get("running", r["state"] == 0 if r.get("state") is not None else None),
                in_depot=r.get("in_depot", False),
                order_count=r.get("order_count", 0),
                orders=orders,
                # The GameScript reports both; leaving them off this list is what made a lost
                # train indistinguishable from a working one in every observation.
                lost=r.get("lost", False),
                idle_reason=r.get("idle_reason", ""),
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

        Merges with existing entries so admin-port financial data (money/loan)
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
            # Accept the GS field names and their older aliases. Live company
            # value and quarter revenue must not be replaced by admin history.
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
            self._apply_quarterly_finance(company, r)
        for cid in list(self.companies.keys()):
            if cid not in seen:
                self.companies[cid].is_active = False
                self._revenue_ledgers.pop(cid, None)
        logger.debug("WorldState: refreshed %d companies from GS", len(seen))

    def apply_gs_company_finance(self, company_id: int, result: dict[str, Any]) -> None:
        """Merge financial data from GS get_company_finance into an existing company entry.

        The GS returns balance, loan, current-quarter revenue and completed
        economy-quarter history. Missing fields preserve existing values.

        The company value is not taken from here. q1_value is the value at the end of
        the last completed quarter, so it reads 0 for the first 91 days and then moves
        four times a year. apply_gs_companies already filled company.value with the
        live figure from CmdGetCompanies, and the score and every observation read that
        field, so overwriting it here reported a quarter-old number as the result.
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
        # Compatibility field: revenue of the last completed economy quarter.
        company.income = _int(result.get("q1_income", result.get("income")), company.income)
        self._apply_quarterly_finance(company, result)

    def _apply_quarterly_finance(self, company: Company, result: dict[str, Any]) -> None:
        """Keep the quarter identity and income from the same GameScript reply."""
        if result.get("q1_income") is not None:
            company.q1_income = int(result["q1_income"])
            company.income = company.q1_income
        if result.get("finance_quarter") is None or result.get("q0_income") is None:
            return
        company.finance_quarter = int(result["finance_quarter"])
        company.finance_date = result.get("finance_date")
        company.q0_income = int(result["q0_income"])
        company.completed_quarter_income = list(result.get("completed_quarter_income", []))
        ledger = self._revenue_ledgers.setdefault(company.id, RevenueLedger())
        company.episode_revenue = ledger.observe(
            company.finance_quarter, company.q0_income, company.completed_quarter_income
        )

    def apply_gs_subsidies(self, results: list[dict[str, Any]]) -> None:
        """Populate subsidies list from GS get_subsidies result."""
        _type_map = {0: "industry", 1: "town"}

        def endpoint_type(value: Any) -> str | None:
            return value if value in ("industry", "town") else _type_map.get(value)

        def endpoint_name(record: dict[str, Any], prefix: str, short: str) -> str | None:
            name = record.get(f"{prefix}_name", record.get(f"{short}_name"))
            if name is None:
                kind = endpoint_type(record.get(f"{prefix}_type", record.get(f"{short}_type")))
                entity_id = record.get(f"{prefix}_index", record.get(f"{short}_id"))
                entity = (self.towns if kind == "town" else self.industries).get(entity_id)
                name = entity.name if entity is not None and kind is not None else None
            return sanitise(name) if name is not None else None

        self.subsidies = [
            Subsidy(
                id=r.get("id", 0),
                cargo_id=r.get("cargo_type", r.get("cargo_id")),
                cargo_label=r.get("cargo_label"),
                src_type=endpoint_type(r.get("source_type", r.get("src_type"))),
                src_id=r.get("source_index", r.get("src_id")),
                src_name=endpoint_name(r, "source", "src"),
                dst_type=endpoint_type(r.get("destination_type", r.get("dst_type"))),
                dst_id=r.get("destination_index", r.get("dst_id")),
                dst_name=endpoint_name(r, "destination", "dst"),
                is_awarded=r.get("is_awarded"),
                # Legacy GS 'remaining' was already in days. Old snapshot
                # 'remaining_years' was fabricated and must not be converted.
                remaining_days=r.get("remaining_days", r.get("remaining")),
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
