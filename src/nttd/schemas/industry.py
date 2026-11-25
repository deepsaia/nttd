from pydantic import BaseModel, Field


class IndustryProduction(BaseModel):
    cargo_id: int = 0
    cargo_label: str = ""
    last_month: int = 0
    transported: int = 0


class IndustryAcceptance(BaseModel):
    cargo_id: int = 0
    cargo_label: str = ""


class NearbyStation(BaseModel):
    """Station anchors within ten Manhattan tiles; no claim of service or catchment."""

    station_id: int
    name: str = ""
    x: int
    y: int
    distance: int = Field(description="Manhattan distance between industry and station anchors, in tiles.")


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
    # None means an older observation did not supply this information; [] is
    # the game's positive statement that this type has no such cargo.
    produces_cargo: list[IndustryAcceptance] | None = None
    accepts_cargo: list[IndustryAcceptance] | None = None
    nearby_stations: list[NearbyStation] | None = None
    nearby_stations_company_id: int | None = Field(
        default=None,
        description="Company whose stations were checked for proximity; null when the source did not identify it.",
    )
