from pydantic import BaseModel


class Company(BaseModel):
    """A company's state as nttd tracks it.

    ``performance_rating`` is OpenTTD's own 0-1000 composite (40% annual cargo
    delivered, 10% profitable vehicles, 10% station coverage, 10% vehicle profit,
    5%+5% quarterly revenue, 5% cargo diversity, 5% cash, 5% no-loan). It is the
    primary benchmark score because it is game-authoritative and hard to game,
    unlike raw company value which is inflated by simply drawing a loan.

    A rating of -1 means OpenTTD has not yet computed one -- it needs a full
    quarter of history, so early in a session it is legitimately absent.
    """

    id: int
    name: str | None = ""
    manager: str = ""
    color: int = 0
    money: int = 0
    loan: int = 0
    max_loan: int = 0
    value: int = 0
    income: int = 0
    profit_last_year: int = 0
    is_ai: bool = False
    is_active: bool = True
    # Scoring fields, emitted by the GS get_companies handler.
    performance_rating: int = -1
    q0_income: int = 0
    q0_expenses: int = 0
    q0_cargo: int = 0
    # The quarter in progress resets to zero at every boundary, and a run ends on one, so
    # q0_cargo is not a total. This is: the GameScript banks each quarter as it ends. Score
    # against it, never against q0_cargo.
    cargo_delivered_total: int = 0
