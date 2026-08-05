"""Time-series metrics queries, over the shared Parquet read path.

Finance and metric series come from the extracted Parquet columns where one exists,
which avoids parsing a full JSON snapshot per row. Anything not extracted, including
every company past the first, falls back to walking snapshot_json.
"""

from __future__ import annotations

import logging
from typing import Any

from nttd.store import parquet_reader

logger = logging.getLogger(__name__)

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

_FINANCE_COLUMNS = {
    "balance": "c0_balance",
    "loan": "c0_loan",
    "income": "c0_income",
    "company_value": "c0_value",
}

# Company fields that describe identity rather than performance, so they are not
# offered as metrics even though they appear on every company record.
_NON_METRIC_FIELDS = ("id", "name", "manager", "color", "is_ai", "is_active")


async def get_metric_series(
    session_id: str,
    metric_name: str,
    company_id: int | None = None,
    from_date: int | None = None,
    to_date: int | None = None,
) -> list[dict[str, Any]]:
    """Return time-series data for a named metric."""
    column = _COLUMN_METRICS.get(metric_name)
    if column and (company_id is None or company_id == 0):
        rows = parquet_reader.read_snapshot_columns(
            session_id, [column], from_date, to_date,
        )
        return [
            {
                "game_date": row["game_date"],
                "company_id": company_id or 0,
                "metric_value": row.get(column),
            }
            for row in rows
        ]

    results = []
    for game_date, snap in parquet_reader.read_snapshots(session_id, from_date, to_date):
        for company in snap.get("companies", []):
            if company_id is not None and company.get("id") != company_id:
                continue
            value = company.get(metric_name)
            if value is not None:
                results.append({
                    "game_date": game_date,
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
    """Return the financial time-series for a company."""
    if company_id == 0:
        rows = parquet_reader.read_snapshot_columns(
            session_id, list(_FINANCE_COLUMNS.values()), from_date, to_date,
        )
        return [
            {
                "game_date": row["game_date"],
                "company_id": 0,
                **{name: row.get(column) for name, column in _FINANCE_COLUMNS.items()},
            }
            for row in rows
        ]

    results = []
    for game_date, snap in parquet_reader.read_snapshots(session_id, from_date, to_date):
        for company in snap.get("companies", []):
            if company.get("id") != company_id:
                continue
            results.append({
                "game_date": game_date,
                "company_id": company_id,
                "balance": company.get("money", 0),
                "loan": company.get("loan", 0),
                "income": company.get("income", 0),
                "company_value": company.get("value", 0),
            })
            break
    return results


async def get_company_latest(session_id: str) -> list[dict[str, Any]]:
    """Return every company as of the most recent snapshot."""
    snap = parquet_reader.latest_snapshot(session_id)
    if snap is None:
        return []
    return snap.get("companies", [])


async def get_available_metrics(session_id: str) -> list[str]:
    """Return the metric names this session can answer for."""
    snapshot = parquet_reader.first_snapshot(session_id)
    if snapshot is None:
        return []

    available = list(_COLUMN_METRICS.keys())
    companies = snapshot.get("companies", [])
    if companies:
        for key in companies[0]:
            if key not in _NON_METRIC_FIELDS and key not in available:
                available.append(key)
    return available
