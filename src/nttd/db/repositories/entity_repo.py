"""Repository for entity snapshot queries -- reads from Parquet.

Game state time-series (towns, industries, stations, vehicles, subsidies) are
stored as full JSON snapshots in Parquet. This module parses the snapshot_json
column to extract entity data for the requested game_date.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

_DATA_DIR = Path("logs/sessions")


def _read_snapshot_at(session_id: str, game_date: int | None = None) -> dict[str, Any] | None:
    """Read the snapshot closest to game_date (or the latest) from Parquet."""
    parquet_path = _DATA_DIR / session_id / "snapshots.parquet"
    if not parquet_path.exists():
        return None

    table = pq.read_table(parquet_path, columns=["game_date", "snapshot_json"])
    if table.num_rows == 0:
        return None

    dates = table.column("game_date").to_pylist()
    jsons = table.column("snapshot_json").to_pylist()

    if game_date is not None:
        target_idx = None
        for i, d in enumerate(dates):
            if d == game_date:
                target_idx = i
                break
        if target_idx is None:
            # Find closest date
            target_idx = min(range(len(dates)), key=lambda i: abs(dates[i] - game_date))
    else:
        target_idx = max(range(len(dates)), key=lambda i: dates[i])

    return json.loads(jsons[target_idx])


def _read_snapshot_history(
    session_id: str, from_date: int | None = None, to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Read all snapshots in a date range from Parquet."""
    parquet_path = _DATA_DIR / session_id / "snapshots.parquet"
    if not parquet_path.exists():
        return []

    table = pq.read_table(parquet_path, columns=["game_date", "snapshot_json"])
    if table.num_rows == 0:
        return []

    results = []
    for i in range(table.num_rows):
        gd = table.column("game_date")[i].as_py()
        if from_date is not None and gd < from_date:
            continue
        if to_date is not None and gd > to_date:
            continue
        results.append(json.loads(table.column("snapshot_json")[i].as_py()))
    return results


async def get_towns_at(session_id: str, game_date: int) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id, game_date)
    if snap is None:
        return []
    return snap.get("towns", [])


async def get_towns_latest(session_id: str) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    return snap.get("towns", [])


async def get_town_history(
    session_id: str, town_id: int, from_date: int | None = None, to_date: int | None = None,
) -> list[dict[str, Any]]:
    snapshots = _read_snapshot_history(session_id, from_date, to_date)
    results = []
    for snap in snapshots:
        for town in snap.get("towns", []):
            if town.get("id") == town_id:
                town["game_date"] = snap.get("game", {}).get("game_date")
                results.append(town)
    return results


async def get_industries_latest(session_id: str) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    return snap.get("industries", [])


async def get_industry_production_latest(session_id: str) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    results = []
    for ind in snap.get("industries", []):
        for prod in ind.get("production", []):
            prod["industry_id"] = ind.get("id")
            results.append(prod)
    return results


async def get_stations_latest(session_id: str, company_id: int | None = None) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    stations = snap.get("stations", [])
    if company_id is not None:
        stations = [s for s in stations if s.get("company_id") == company_id]
    return stations


async def get_station_cargo_latest(session_id: str, station_id: int) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    for station in snap.get("stations", []):
        if station.get("id") == station_id:
            return station.get("cargo_waiting", [])
    return []


async def get_vehicles_latest(session_id: str, company_id: int | None = None) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    vehicles = snap.get("vehicles", [])
    if company_id is not None:
        vehicles = [v for v in vehicles if v.get("company_id") == company_id]
    return vehicles


async def get_vehicle_orders_latest(session_id: str, vehicle_id: int) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    for vehicle in snap.get("vehicles", []):
        if vehicle.get("id") == vehicle_id:
            return vehicle.get("orders", [])
    return []


async def get_subsidies_latest(session_id: str) -> list[dict[str, Any]]:
    snap = _read_snapshot_at(session_id)
    if snap is None:
        return []
    return snap.get("subsidies", [])
