import hashlib

from pydantic import BaseModel


def make_route_id(company_id: int, vehicle_type: str, station_ids: tuple[int, ...]) -> str:
    """Deterministic route ID from station set. Sorted so (A->B) == (B->A)."""
    key = f"{company_id}:{vehicle_type}:{','.join(str(s) for s in sorted(station_ids))}"
    return f"rt_{hashlib.md5(key.encode()).hexdigest()[:8]}"


class Route(BaseModel):
    """A transport line: one or more vehicles repeatedly visiting the same ordered set of stations.

    Derived from vehicle orders during each GS refresh -- not stored in OpenTTD directly.
    Multiple vehicles with identical station sequences are grouped into one Route.
    """

    route_id: str
    company_id: int
    vehicle_type: str
    station_ids: list[int]
    status: str = "active"
    vehicle_ids: list[int] = []
    depot_tile: int = 0
    vehicle_count: int = 0
    total_profit_this_year: int = 0
    total_profit_last_year: int = 0
    created_at: int = 0
    path_tiles: list[int] = []
    track_confirmed_at: int = 0
    first_vehicle_at: int = 0
