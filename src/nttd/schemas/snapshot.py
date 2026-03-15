from pydantic import BaseModel

from nttd.schemas.company import Company
from nttd.schemas.game import GameState
from nttd.schemas.industry import Industry
from nttd.schemas.route import Route
from nttd.schemas.station import Station
from nttd.schemas.subsidy import Subsidy
from nttd.schemas.town import Town
from nttd.schemas.vehicle import Vehicle


class StateSnapshot(BaseModel):
    game: GameState = GameState()
    companies: list[Company] = []
    towns: list[Town] = []
    industries: list[Industry] = []
    stations: list[Station] = []
    vehicles: list[Vehicle] = []
    routes: list[Route] = []
    subsidies: list[Subsidy] = []
