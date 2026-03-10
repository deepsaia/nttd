from enum import StrEnum

from pydantic import BaseModel


class VehicleType(StrEnum):
    TRAIN = "train"
    ROAD = "road"
    SHIP = "ship"
    AIR = "air"


class Order(BaseModel):
    station_id: int = 0
    order_type: str = ""


class Vehicle(BaseModel):
    id: int
    type: VehicleType = VehicleType.TRAIN
    company_id: int = 0
    name: str = ""
    profit_this_year: int = 0
    profit_last_year: int = 0
    age: int = 0
    running: bool = True
    orders: list[Order] = []
