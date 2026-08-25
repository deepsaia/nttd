"""One company's series, as plain rows, for drawing a trend.

The board publishes this as ``trajectories.parquet`` and its page charts a run from it. Ten
integers a tick is a far cheaper thing to hand a plotting library than the whole world as
JSON, and the bundle carries ``snapshots.parquet`` regardless, so nothing needs this to
VERIFY a run: it exists to be drawn.

It used to live in a much larger module of derived business metrics, which went because every
figure in it was computed from game data already on the page. This came out with it and should
not have: it derives nothing. It is a projection of what the game reported, one row per
snapshot, and the board had been reading it all along.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Read off each company, and named as the game names them. income and expenses are the
# quarter IN PROGRESS, which is what the game exposes.
_FIELDS: tuple[tuple[str, str], ...] = (
    ("value", "value"),
    ("money", "money"),
    ("loan", "loan"),
    ("max_loan", "max_loan"),
    ("income", "q0_income"),
    ("expenses", "q0_expenses"),
    # The RUN TOTAL, banked by the GameScript across quarter boundaries, not the quarter in
    # progress. q0_cargo resets at every boundary and a run ENDS on one, so a measured run
    # that delivered 3,526 units over its year charted as zero.
    ("cargo", "cargo_delivered_total"),
    ("vehicles", "vehicles"),
    ("stations", "stations"),
    ("profitable_vehicles", "profitable_vehicles"),
    ("idle_vehicles", "idle_vehicles"),
    ("maintenance", "maintenance"),
)


def trajectory_rows(session_dir: Path, company_id: int) -> list[dict[str, int]]:
    """Every snapshot's figures for one company, oldest first.

    Empty rather than raising when the series is missing or unreadable: a run whose
    snapshots did not survive still has a score worth publishing, and a verdict that fails
    to write because a chart could not be drawn is the wrong trade.

    Reads ``snapshot_json`` rather than the typed ``c0_*`` columns, which cover company 0
    only and carry no expenses. Measured at 41ms for 340 snapshots.
    """
    path = session_dir / "snapshots.parquet"
    if not path.exists():
        return []

    try:
        import pyarrow.parquet as pq  # noqa: PLC0415

        rows = pq.read_table(path, columns=["game_date", "snapshot_json"]).to_pylist()
    except Exception:
        logger.exception("Could not read %s", path)
        return []

    out: list[dict[str, int]] = []
    for row in rows:
        company = _company_in(row.get("snapshot_json"), company_id)
        if company is None:
            continue
        point = {"game_date": int(row.get("game_date") or 0)}
        for name, source in _FIELDS:
            point[name] = int(company.get(source) or 0)
        out.append(point)
    return out


def _company_in(raw: Any, company_id: int) -> dict[str, Any] | None:
    """The company's own block in one snapshot, or None if it is not in it.

    A snapshot taken before the company existed, or one written torn, is skipped rather
    than contributing a row of zeros that would draw as a collapse.
    """
    if not raw:
        return None
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return next(
        (c for c in snapshot.get("companies") or [] if c.get("id") == company_id), None,
    )
