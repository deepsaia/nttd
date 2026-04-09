from pydantic import BaseModel


class IndustryProduction(BaseModel):
    cargo_id: int = 0
    cargo_label: str = ""
    last_month: int = 0
    transported: int = 0


class IndustryAcceptance(BaseModel):
    cargo_id: int = 0
    cargo_label: str = ""


class Industry(BaseModel):
    id: int
    name: str = ""
    type_id: int = 0
    type_name: str = ""
    x: int = 0
    y: int = 0
    is_raw: bool = False
    is_processing: bool = False
    production: list[IndustryProduction] = []
    accepted: list[IndustryAcceptance] = []
