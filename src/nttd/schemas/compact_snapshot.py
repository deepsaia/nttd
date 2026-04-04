from pydantic import BaseModel, Field


class CompactVehicleCounts(BaseModel):
    total: int = 0
    in_depot: int = 0
    avg_profit_this_year: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class CompactCompany(BaseModel):
    id: int
    name: str | None = ""
    balance: int = 0
    loan: int = 0
    income: int = 0
    profit_last_year: int = 0
    company_value: int = 0
    profit_trend: list[int] = Field(default_factory=list)


class CompactRoute(BaseModel):
    route_id: int
    vehicle_type: str
    station_ids: list[int]
    vehicle_count: int = 0
    total_profit_this_year: int = 0


class CompactSubsidy(BaseModel):
    id: int
    cargo_label: str = ""
    src_name: str = ""
    dst_name: str = ""
    value: int = 0
    remaining_years: int = 0


class CompactStation(BaseModel):
    id: int
    name: str = ""
    cargo_total: int = 0


class CompactTown(BaseModel):
    id: int
    name: str = ""
    population: int = 0


class CompactRecentAction(BaseModel):
    action_id: str
    action_type: str
    status: str
    company_id: int = 0


class CompactSnapshot(BaseModel):
    game_date: int = 0
    paused: bool = False
    mode: str = ""
    map_width: int = 0
    map_height: int = 0
    company: CompactCompany | None = None
    vehicles: CompactVehicleCounts = Field(default_factory=CompactVehicleCounts)
    routes: list[CompactRoute] = Field(default_factory=list)
    subsidies: list[CompactSubsidy] = Field(default_factory=list)
    top_stations: list[CompactStation] = Field(default_factory=list)
    top_towns: list[CompactTown] = Field(default_factory=list)
    total_stations: int = 0
    total_towns: int = 0
    total_routes: int = 0
    recent_actions: list[CompactRecentAction] = Field(default_factory=list)
