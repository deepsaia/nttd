from pydantic import BaseModel


class IndustryProduction(BaseModel):
    cargo_type: str = ""
    amount: int = 0


class Industry(BaseModel):
    id: int
    type: str = ""
    x: int = 0
    y: int = 0
    production: list[IndustryProduction] = []
