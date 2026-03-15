from pydantic import BaseModel


class Route(BaseModel):
    """A transport line: one or more vehicles repeatedly visiting the same ordered set of stations.

    Derived from vehicle orders during each GS refresh — not stored in OpenTTD directly.
    Multiple vehicles with identical station sequences are grouped into one Route.
    """

    route_id: int
    company_id: int
    vehicle_type: str
    station_ids: list[int]
    vehicle_count: int = 0
    total_profit_this_year: int = 0
    total_profit_last_year: int = 0
