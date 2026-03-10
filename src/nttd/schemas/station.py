from pydantic import BaseModel


class CargoWaiting(BaseModel):
    cargo_type: str = ""
    amount: int = 0


class Station(BaseModel):
    id: int
    name: str = ""
    company_id: int = 0
    x: int = 0
    y: int = 0
    cargo_waiting: list[CargoWaiting] = []
