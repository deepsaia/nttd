from enum import StrEnum

from pydantic import BaseModel


class VehicleType(StrEnum):
    TRAIN = "train"
    ROAD = "road"
    SHIP = "ship"
    AIR = "aircraft"


class Order(BaseModel):
    index: int = 0
    destination: int = 0
    flags: int = 0
    is_goto_station: bool = False
    is_goto_depot: bool = False
    is_goto_waypoint: bool = False


class Vehicle(BaseModel):
    id: int
    type: str = "train"
    company_id: int = 0
    name: str = ""
    engine_id: int = 0
    x: int = 0
    y: int = 0
    profit_this_year: int = 0
    profit_last_year: int = 0
    age: int = 0
    max_age: int = 0
    capacity: int = 0
    current_speed: int = 0
    state: int = 0
    running: bool = True
    in_depot: bool = False
    order_count: int = 0
    orders: list[Order] = []
