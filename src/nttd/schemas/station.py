from pydantic import BaseModel


class CargoWaiting(BaseModel):
    cargo_id: int = 0
    cargo_label: str = ""
    waiting: int = 0


class Station(BaseModel):
    id: int
    name: str = ""
    company_id: int = 0
    x: int = 0
    y: int = 0
    has_rail: bool = False
    has_truck: bool = False
    has_bus: bool = False
    has_airport: bool = False
    has_dock: bool = False
    cargo_waiting: list[CargoWaiting] = []
