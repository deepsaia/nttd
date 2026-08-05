"""Entity snapshot queries, over the shared Parquet read path.

Game state time-series (towns, industries, stations, vehicles, subsidies) are
recorded as full JSON snapshots, so every query here is a lookup into one snapshot
or a walk across a date range of them.
"""

from __future__ import annotations

import logging
from typing import Any

from nttd.db import parquet_reader

logger = logging.getLogger(__name__)


def _latest(session_id: str) -> dict[str, Any]:
    """Return the most recent snapshot, or an empty one if nothing is recorded.

    An empty dict rather than None so callers can go straight to .get(): a session
    with no snapshots yet has no entities, which is the same answer.
    """
    return parquet_reader.latest_snapshot(session_id) or {}


async def get_towns_at(session_id: str, game_date: int) -> list[dict[str, Any]]:
    snap = parquet_reader.snapshot_at(session_id, game_date) or {}
    return snap.get("towns", [])


async def get_towns_latest(session_id: str) -> list[dict[str, Any]]:
    return _latest(session_id).get("towns", [])


async def get_town_history(
    session_id: str, town_id: int, from_date: int | None = None, to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Return one town's state at each snapshot in a date range."""
    results = []
    for game_date, snap in parquet_reader.read_snapshots(session_id, from_date, to_date):
        for town in snap.get("towns", []):
            if town.get("id") == town_id:
                # The indexed column rather than the nested game.game_date field:
                # it is the value the date filter matched on, so a row can never
                # report a date the caller did not ask for.
                town["game_date"] = game_date
                results.append(town)
    return results


async def get_industries_latest(session_id: str) -> list[dict[str, Any]]:
    return _latest(session_id).get("industries", [])


async def get_industry_production_latest(session_id: str) -> list[dict[str, Any]]:
    results = []
    for ind in _latest(session_id).get("industries", []):
        for prod in ind.get("production", []):
            prod["industry_id"] = ind.get("id")
            results.append(prod)
    return results


async def get_stations_latest(
    session_id: str, company_id: int | None = None,
) -> list[dict[str, Any]]:
    stations = _latest(session_id).get("stations", [])
    if company_id is not None:
        stations = [s for s in stations if s.get("company_id") == company_id]
    return stations


async def get_station_cargo_latest(session_id: str, station_id: int) -> list[dict[str, Any]]:
    for station in _latest(session_id).get("stations", []):
        if station.get("id") == station_id:
            return station.get("cargo_waiting", [])
    return []


async def get_vehicles_latest(
    session_id: str, company_id: int | None = None,
) -> list[dict[str, Any]]:
    vehicles = _latest(session_id).get("vehicles", [])
    if company_id is not None:
        vehicles = [v for v in vehicles if v.get("company_id") == company_id]
    return vehicles


async def get_vehicle_orders_latest(session_id: str, vehicle_id: int) -> list[dict[str, Any]]:
    for vehicle in _latest(session_id).get("vehicles", []):
        if vehicle.get("id") == vehicle_id:
            return vehicle.get("orders", [])
    return []


async def get_subsidies_latest(session_id: str) -> list[dict[str, Any]]:
    return _latest(session_id).get("subsidies", [])
