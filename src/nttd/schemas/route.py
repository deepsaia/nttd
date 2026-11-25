import hashlib

from pydantic import BaseModel


def make_route_id(company_id: int, vehicle_type: str, station_ids: tuple[int, ...]) -> str:
    """Deterministic route ID from station set. Sorted so (A->B) == (B->A)."""
    key = f"{company_id}:{vehicle_type}:{','.join(str(s) for s in sorted(set(station_ids)))}"
    return f"rt_{hashlib.md5(key.encode()).hexdigest()[:8]}"


class Route(BaseModel):
    """A transport line: vehicles repeatedly visiting the same set of stations.

    Derived from vehicle orders during each GS refresh -- not stored in OpenTTD directly.
    Opposite or differing station sequences share a report without losing any vehicles;
    connectivity checks cover each vehicle's actual repeating sequence.

    The game accepts an order to a station that no road or track reaches, so holding the
    orders proves nothing about the path. ``track_confirmed_at`` is set only when the game
    walked the built road or rail between the stations and reached the far end, or when a
    connect_rail action built it. ``vehicles_without_path`` lists the vehicles that cannot
    reach their first ordered station, for example trucks in a depot that no road joins.
    ``vehicles_with_unknown_path`` distinguishes an unfinished check from a failed one.
    Confirmations expire or are invalidated when infrastructure or orders change.
    ``status`` follows from the facts:

    - ``unchecked``: some path checks are missing, expired, or inconclusive.
    - ``unconnected``: vehicles hold the orders; the game found no path between the
      stations, or a vehicle cannot reach them.
    - ``active``: vehicles hold the orders, the stations are joined, and every vehicle can
      reach them.
    - ``track_built``: the stations are joined and no vehicle holds the orders.
    - ``planned``: registered ahead of any vehicle or track.
    - ``removed``: a station is gone, or the vehicles left before any path was confirmed.
    """

    route_id: str
    company_id: int
    vehicle_type: str
    station_ids: list[int]
    status: str = "unchecked"
    vehicle_ids: list[int] = []
    depot_tile: int = 0
    vehicle_count: int = 0
    total_profit_this_year: int = 0
    total_profit_last_year: int = 0
    created_at: int = 0
    path_tiles: list[int] = []
    track_confirmed_at: int = 0
    connection_checked_at: int = 0
    vehicles_without_path: list[int] = []
    vehicles_with_unknown_path: list[int] = []
    first_vehicle_at: int = 0

    def refresh_status(self) -> None:
        """Set ``status`` from the vehicles, the path check and the confirmation."""
        if self.status == "removed":
            return
        if self.vehicle_ids:
            if self.vehicles_without_path:
                self.status = "unconnected"
            elif self.track_confirmed_at and not self.vehicles_with_unknown_path:
                self.status = "active"
            elif self.connection_checked_at and not self.track_confirmed_at:
                self.status = "unconnected"
            else:
                self.status = "unchecked"
        elif self.track_confirmed_at:
            self.status = "track_built"
        elif self.status != "planned":
            self.status = "removed"
