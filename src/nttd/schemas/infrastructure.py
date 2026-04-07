from pydantic import BaseModel


class InfrastructureCosts(BaseModel):
    company_id: int = 0
    rail_pieces: int = 0
    road_pieces: int = 0
    water_pieces: int = 0
    station_pieces: int = 0
    airport_pieces: int = 0
    rail_cost: int = 0
    road_cost: int = 0
    water_cost: int = 0
    station_cost: int = 0
    airport_cost: int = 0
