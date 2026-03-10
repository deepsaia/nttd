import uuid

from nttd.schemas.company import Company
from nttd.schemas.game import GameState, RuntimeMode
from nttd.schemas.industry import Industry
from nttd.schemas.snapshot import StateSnapshot
from nttd.schemas.station import Station
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Vehicle


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
