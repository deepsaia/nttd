from pydantic import BaseModel


class CargoFlow(BaseModel):
    company_id: int = 0
    cargo_id: int = 0
    entity_type: str = ""
    entity_id: int = 0
    direction: str = ""
    amount: int = 0
