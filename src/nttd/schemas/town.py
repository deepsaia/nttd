from pydantic import BaseModel


class Town(BaseModel):
    id: int
    name: str = ""
    population: int = 0
    x: int = 0
    y: int = 0
