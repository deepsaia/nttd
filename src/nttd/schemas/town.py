from pydantic import BaseModel


class Town(BaseModel):
    id: int
    name: str = ""
    population: int = 0
    houses: int | None = None
    x: int = 0
    y: int = 0
    is_city: bool | None = None
    growth_rate: int | None = None
