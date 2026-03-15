import logging
import uuid
from typing import Any

from nttd.schemas.company import Company
from nttd.schemas.game import GameState, RuntimeMode
from nttd.schemas.industry import Industry, IndustryProduction
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.station import CargoWaiting, Station
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Order, Vehicle

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

    def snapshot(self) -> StateSnapshot:
        self.game.snapshot_id = uuid.uuid4().hex[:12]
        return StateSnapshot(
            game=self.game.model_copy(),
            companies=list(self.companies.values()),
            towns=list(self.towns.values()),
            industries=list(self.industries.values()),
            stations=list(self.stations.values()),
            vehicles=list(self.vehicles.values()),
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
                name=r.get("name", ""),
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
            self.industries[iid] = Industry(
                id=iid,
                name=r.get("name", ""),
                type_id=r.get("type_id", 0),
                type_name=r.get("type_name", ""),
                x=r.get("x", 0),
                y=r.get("y", 0),
                is_raw=r.get("is_raw", False),
                is_processing=r.get("is_processing", False),
                production=production,
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
            self.stations[sid] = Station(
                id=sid,
                name=r.get("name", ""),
                company_id=company_id,
                x=r.get("x", 0),
                y=r.get("y", 0),
                has_rail=r.get("has_rail", False),
                has_truck=r.get("has_truck", False),
                has_bus=r.get("has_bus", False),
                has_airport=r.get("has_airport", False),
                has_dock=r.get("has_dock", False),
                cargo_waiting=cargo_waiting,
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
                name=r.get("name", ""),
                engine_id=r.get("engine_id", 0),
                x=r.get("x", 0),
                y=r.get("y", 0),
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
        logger.debug("WorldState: refreshed %d vehicles for company %d", len(seen), company_id)
