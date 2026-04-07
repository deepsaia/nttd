"""Repository for time-series metrics queries -- reads from Parquet.

Finance and metric time-series are extracted from the columnar Parquet file
for fast dashboard access. Falls back to parsing snapshot_json for detailed
queries not covered by the extracted columns.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

_DATA_DIR = Path("logs/sessions")

# Metric names that map to extracted Parquet columns (no JSON parsing needed)
_COLUMN_METRICS = {
    "balance": "c0_balance",
    "loan": "c0_loan",
    "income": "c0_income",
    "company_value": "c0_value",
    "num_vehicles": "num_vehicles",
    "num_stations": "num_stations",
    "num_towns": "num_towns",
    "num_companies": "num_companies",
}


async def get_metric_series(
    session_id: str,
    metric_name: str,
    company_id: int | None = None,
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Return time-series data for a named metric."""
    parquet_path = _DATA_DIR / session_id / "snapshots.parquet"
    if not parquet_path.exists():
        return []

    col_name = _COLUMN_METRICS.get(metric_name)
    if col_name and (company_id is None or company_id == 0):
        columns = ["game_date", col_name]
        table = pq.read_table(parquet_path, columns=columns)
        results = []
        for i in range(table.num_rows):
            gd = table.column("game_date")[i].as_py()
            if from_date is not None and gd < from_date:
                continue
            if to_date is not None and gd > to_date:
                continue
            results.append({
                "game_date": gd,
                "company_id": company_id or 0,
                "metric_value": table.column(col_name)[i].as_py(),
            })
        return results

    # Fallback: parse snapshot_json
    table = pq.read_table(parquet_path, columns=["game_date", "snapshot_json"])
    results = []
    for i in range(table.num_rows):
        gd = table.column("game_date")[i].as_py()
        if from_date is not None and gd < from_date:
            continue
        if to_date is not None and gd > to_date:
            continue
        snap = json.loads(table.column("snapshot_json")[i].as_py())
        for company in snap.get("companies", []):
            if company_id is not None and company.get("id") != company_id:
                continue
            value = company.get(metric_name)
            if value is not None:
                results.append({
                    "game_date": gd,
                    "company_id": company.get("id"),
                    "metric_value": value,
                })
    return results


async def get_finance_series(
    session_id: str,
    company_id: int,
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Return financial time-series for a company."""
    parquet_path = _DATA_DIR / session_id / "snapshots.parquet"
    if not parquet_path.exists():
        return []

    if company_id == 0:
        columns = ["game_date", "c0_balance", "c0_loan", "c0_income", "c0_value"]
        table = pq.read_table(parquet_path, columns=columns)
        results = []
        for i in range(table.num_rows):
            gd = table.column("game_date")[i].as_py()
            if from_date is not None and gd < from_date:
                continue
            if to_date is not None and gd > to_date:
                continue
            results.append({
                "game_date": gd,
                "company_id": 0,
                "balance": table.column("c0_balance")[i].as_py(),
                "loan": table.column("c0_loan")[i].as_py(),
                "income": table.column("c0_income")[i].as_py(),
                "company_value": table.column("c0_value")[i].as_py(),
            })
        return results

    # For non-zero companies, parse snapshot_json
    table = pq.read_table(parquet_path, columns=["game_date", "snapshot_json"])
    results = []
    for i in range(table.num_rows):
        gd = table.column("game_date")[i].as_py()
        if from_date is not None and gd < from_date:
            continue
        if to_date is not None and gd > to_date:
            continue
        snap = json.loads(table.column("snapshot_json")[i].as_py())
        for company in snap.get("companies", []):
            if company.get("id") == company_id:
                results.append({
                    "game_date": gd,
                    "company_id": company_id,
                    "balance": company.get("money", 0),
                    "loan": company.get("loan", 0),
                    "income": company.get("income", 0),
                    "company_value": company.get("value", 0),
                })
                break
    return results


async def get_company_latest(session_id: str) -> list[dict[str, Any]]:
    """Return latest snapshot for each company in a session."""
    parquet_path = _DATA_DIR / session_id / "snapshots.parquet"
    if not parquet_path.exists():
        return []

    table = pq.read_table(parquet_path, columns=["game_date", "snapshot_json"])
    if table.num_rows == 0:
        return []

    # Find the row with the max game_date
    dates = table.column("game_date").to_pylist()
    max_idx = max(range(len(dates)), key=lambda i: dates[i])
    snap = json.loads(table.column("snapshot_json")[max_idx].as_py())
    return snap.get("companies", [])


async def get_available_metrics(session_id: str) -> list[str]:
    """Return available metric names for a session."""
    parquet_path = _DATA_DIR / session_id / "snapshots.parquet"
    if not parquet_path.exists():
        return []

    available = list(_COLUMN_METRICS.keys())

    # Check snapshot_json for company-level fields
    table = pq.read_table(parquet_path, columns=["snapshot_json"])
    if table.num_rows > 0:
        snap = json.loads(table.column("snapshot_json")[0].as_py())
        companies = snap.get("companies", [])
        if companies:
            for key in companies[0]:
                if key not in ("id", "name", "manager", "color", "is_ai", "is_active"):
                    if key not in available:
                        available.append(key)
    return available
