from pydantic import BaseModel


class Town(BaseModel):
    id: int
    name: str = ""
    population: int = 0
    houses: int = 0
    x: int = 0
    y: int = 0
    is_city: bool = False
    growth_rate: int = 0
