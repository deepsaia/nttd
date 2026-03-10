from pydantic import BaseModel


class Company(BaseModel):
    id: int
    name: str = ""
    manager: str = ""
    color: int = 0
    money: int = 0
    loan: int = 0
    value: int = 0
    income: int = 0
    is_ai: bool = False
    is_active: bool = True
