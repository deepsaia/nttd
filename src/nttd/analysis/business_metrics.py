"""What the run says about running a business, derived from the traces.

The score is OpenTTD's performance rating, which is game-authoritative and stays the
ranking metric. It says how well the company did, not how it was run: an operator that
borrowed to the limit, ran at a loss for three years and recovered scores the same as one
that compounded steadily to the same place.

Nothing here is newly recorded. Every value comes from ``snapshots.parquet``, which
already holds the full state per tick, and ``actions.parquet``. That matters beyond
convenience: because these are pure functions of artifacts that travel inside the
submission bundle, whoever verifies a run can recompute them and compare. They are
evidence rather than claims, which self-reported cost can never be.

**Expenses are negative.** ``GSCompany.GetQuarterlyExpenses`` reports them as negative
money, confirmed across 1,626 recorded samples with no positive case. So profit is
``income + expenses``, and writing the subtraction that reads naturally would invert
every margin in the file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bumped when a formula changes, so a board can tell which rows are comparable. The
# score has its own version; this is a separate thing that can move independently.
METRICS_VERSION = "v1"

@dataclass
class BusinessMetrics:
    """One company's run, described as a business rather than a score.

    Every field is either an endpoint value or a run-wide summary, and where both are
    useful both are present. Peak and final borrowing answer different questions: a
    company that ran the whole game at 90 percent of its credit and repaid in the last
    quarter looks prudent on the endpoint alone.
    """

    metrics_version: str = METRICS_VERSION

    # Profitability
    operating_margin_final: float = 0.0
    operating_margin_mean: float = 0.0
    profitable_quarters_share: float = 0.0
    maintenance_burden_final: float = 0.0
    maintenance_burden_mean: float = 0.0

    # Capital efficiency
    return_on_capital: float = 0.0
    peak_capital_deployed: int = 0

    # Growth
    value_at_25pct: int = 0
    value_at_50pct: int = 0
    value_at_75pct: int = 0
    cargo_at_25pct: int = 0
    cargo_at_50pct: int = 0
    cargo_at_75pct: int = 0
    days_to_first_profit: int = -1

    # Risk and leverage
    peak_credit_used: float = 0.0
    final_credit_used: float = 0.0
    min_cash: int = 0
    ended_in_debt: bool = False

    # Operations
    profitable_vehicle_share: float = 0.0
    idle_vehicle_share: float = 0.0
    vehicles_final: int = 0
    stations_final: int = 0
    cargo_per_vehicle: float = 0.0
    cargo_per_station: float = 0.0

    # Decision economy
    action_success_rate: float = 0.0
    value_per_action: float = 0.0
    usd_per_score_point: float = 0.0

    def as_row(self) -> dict[str, Any]:
        """Flatten for result.parquet."""
        return asdict(self)


@dataclass
class _CompanySeries:
    """One company's values over the run, in snapshot order."""

    game_dates: list[int] = field(default_factory=list)
    value: list[int] = field(default_factory=list)
    money: list[int] = field(default_factory=list)
    loan: list[int] = field(default_factory=list)
    income: list[int] = field(default_factory=list)
    expenses: list[int] = field(default_factory=list)
    cargo: list[int] = field(default_factory=list)
    max_loan: list[int] = field(default_factory=list)
    maintenance: list[int] = field(default_factory=list)
    vehicles: list[int] = field(default_factory=list)
    profitable_vehicles: list[int] = field(default_factory=list)
    idle_vehicles: list[int] = field(default_factory=list)
    stations: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.game_dates)


def compute(
    session_dir: Path,
    company_id: int,
    primary_score: int = 0,
    total_cost_usd: float = 0.0,
    total_actions: int = 0,
    successful_actions: int = 0,
) -> BusinessMetrics:
    """Derive one company's business metrics from a finished session's traces.

    Returns zeroed metrics rather than raising when the traces are missing or
    unreadable: a run whose snapshots did not survive still has a score worth
    recording, and a result row that fails to write is worse than one with empty
    columns.
    """
    series = _read_series(session_dir, company_id)
    metrics = BusinessMetrics()

    if not series:
        logger.warning(
            "No snapshot series for company %d in %s, business metrics left empty",
            company_id, session_dir.name,
        )
        return _decision_economy(
            metrics, primary_score, total_cost_usd, total_actions, successful_actions, 0,
        )

    _profitability(metrics, series)
    _capital(metrics, series)
    _growth(metrics, series)
    _risk(metrics, series)
    _operations(metrics, series)
    return _decision_economy(
        metrics, primary_score, total_cost_usd, total_actions, successful_actions,
        series.value[-1] if series.value else 0,
    )


def _read_series(session_dir: Path, company_id: int) -> _CompanySeries | None:
    """Pull one company out of every snapshot.

    The typed ``c0_*`` columns cover only company 0 and not expenses, so this reads
    ``snapshot_json``. Measured at 41ms for 340 snapshots, which is nothing at session
    end, and it keeps the reader correct for any company rather than only the first.
    """
    path = session_dir / "snapshots.parquet"
    if not path.exists():
        return None

    try:
        import pyarrow.parquet as pq  # noqa: PLC0415

        rows = pq.read_table(path, columns=["game_date", "snapshot_json"]).to_pylist()
    except Exception:
        logger.exception("Could not read %s", path)
        return None

    series = _CompanySeries()
    for row in rows:
        raw = row.get("snapshot_json")
        if not raw:
            continue
        try:
            snapshot = json.loads(raw)
        except json.JSONDecodeError:
            continue

        company = next(
            (c for c in snapshot.get("companies", []) if c.get("id") == company_id), None,
        )
        if company is None:
            continue

        series.game_dates.append(int(row.get("game_date") or 0))
        series.value.append(int(company.get("value") or 0))
        series.money.append(int(company.get("money") or 0))
        series.loan.append(int(company.get("loan") or 0))
        series.max_loan.append(int(company.get("max_loan") or 0))
        series.income.append(int(company.get("q0_income") or 0))
        series.expenses.append(int(company.get("q0_expenses") or 0))
        series.cargo.append(int(company.get("q0_cargo") or 0))
        series.maintenance.append(_maintenance(snapshot, company_id))

        owned = [v for v in snapshot.get("vehicles", []) if v.get("company_id") == company_id]
        series.vehicles.append(len(owned))
        series.profitable_vehicles.append(
            sum(1 for v in owned if int(v.get("profit_this_year") or 0) > 0)
        )
        series.idle_vehicles.append(
            sum(1 for v in owned if v.get("in_depot") and not v.get("running"))
        )
        series.stations.append(
            sum(1 for s in snapshot.get("stations", []) if s.get("company_id") == company_id)
        )

    return series if len(series) else None


def _maintenance(snapshot: dict[str, Any], company_id: int) -> int:
    """Monthly infrastructure upkeep for one company."""
    total = 0
    for entry in snapshot.get("infrastructure", []):
        if entry.get("company_id") != company_id:
            continue
        for key, value in entry.items():
            if key.endswith("_cost") and isinstance(value, int):
                total += value
    return total


def _profitability(metrics: BusinessMetrics, series: _CompanySeries) -> None:
    """Margin and how much of revenue upkeep eats.

    Expenses are negative, so profit adds them. Quarters with no revenue are skipped
    rather than counted as a margin of zero, which would drag the mean toward zero for
    a company that simply had not started earning yet.
    """
    margins = [
        (income + expense) / income
        for income, expense in zip(series.income, series.expenses)
        if income > 0
    ]
    if margins:
        metrics.operating_margin_final = round(margins[-1], 4)
        metrics.operating_margin_mean = round(sum(margins) / len(margins), 4)

    earning = [
        index for index, income in enumerate(series.income) if income > 0
    ]
    if earning:
        profitable = sum(
            1 for index in earning if series.income[index] + series.expenses[index] > 0
        )
        metrics.profitable_quarters_share = round(profitable / len(earning), 4)

    burdens = [
        upkeep / income
        for upkeep, income in zip(series.maintenance, series.income)
        if income > 0 and upkeep > 0
    ]
    if burdens:
        metrics.maintenance_burden_final = round(burdens[-1], 4)
        metrics.maintenance_burden_mean = round(sum(burdens) / len(burdens), 4)


def _capital(metrics: BusinessMetrics, series: _CompanySeries) -> None:
    """What the company made of the money it commanded.

    Capital deployed is the most it ever had available at once: cash plus what it had
    borrowed. Value gained is measured against the start, so a company handed a large
    starting balance is not credited with it.
    """
    peak = max(
        (cash + debt for cash, debt in zip(series.money, series.loan)), default=0,
    )
    metrics.peak_capital_deployed = int(peak)
    gained = (series.value[-1] - series.value[0]) if series.value else 0
    if peak > 0:
        metrics.return_on_capital = round(gained / peak, 4)


def _growth(metrics: BusinessMetrics, series: _CompanySeries) -> None:
    """The shape of the run, not just where it ended."""
    count = len(series)
    for fraction, value_field, cargo_field in (
        (0.25, "value_at_25pct", "cargo_at_25pct"),
        (0.50, "value_at_50pct", "cargo_at_50pct"),
        (0.75, "value_at_75pct", "cargo_at_75pct"),
    ):
        index = min(int(count * fraction), count - 1)
        setattr(metrics, value_field, series.value[index])
        setattr(metrics, cargo_field, series.cargo[index])

    for index, (income, expense) in enumerate(zip(series.income, series.expenses)):
        if income > 0 and income + expense > 0:
            metrics.days_to_first_profit = series.game_dates[index] - series.game_dates[0]
            break


def _risk(metrics: BusinessMetrics, series: _CompanySeries) -> None:
    """How much of the result was borrowed, and how close it ran to the edge.

    Debt is measured against the credit available, not against company value. Value is
    a poor denominator here: OpenTTD reports it as 0 or 1 until a company owns enough
    to be worth something, so debt-to-value produced a peak leverage of 250,000 on a
    real session, and a guard of ``value > 0`` does not catch a value of 1.

    Credit utilisation is bounded, defined from the first tick, and answers the
    question that matters: how much of what it could borrow did it actually draw.
    """
    used = [
        debt / ceiling
        for debt, ceiling in zip(series.loan, series.max_loan)
        if ceiling > 0
    ]
    if used:
        metrics.peak_credit_used = round(max(used), 4)
        metrics.final_credit_used = round(used[-1], 4)
    metrics.min_cash = min(series.money) if series.money else 0
    metrics.ended_in_debt = bool(series.loan and series.loan[-1] > 0)


def _operations(metrics: BusinessMetrics, series: _CompanySeries) -> None:
    """Whether the assets were doing anything useful."""
    metrics.vehicles_final = series.vehicles[-1] if series.vehicles else 0
    metrics.stations_final = series.stations[-1] if series.stations else 0

    if metrics.vehicles_final:
        metrics.profitable_vehicle_share = round(
            series.profitable_vehicles[-1] / metrics.vehicles_final, 4,
        )
        metrics.idle_vehicle_share = round(
            series.idle_vehicles[-1] / metrics.vehicles_final, 4,
        )

    delivered = series.cargo[-1] if series.cargo else 0
    if metrics.vehicles_final:
        metrics.cargo_per_vehicle = round(delivered / metrics.vehicles_final, 2)
    if metrics.stations_final:
        metrics.cargo_per_station = round(delivered / metrics.stations_final, 2)


def _decision_economy(
    metrics: BusinessMetrics,
    primary_score: int,
    total_cost_usd: float,
    total_actions: int,
    successful_actions: int,
    final_value: int,
) -> BusinessMetrics:
    """What the decisions cost, in actions and in money."""
    if total_actions > 0:
        metrics.action_success_rate = round(successful_actions / total_actions, 4)
        metrics.value_per_action = round(final_value / total_actions, 2)
    if primary_score > 0 and total_cost_usd > 0:
        metrics.usd_per_score_point = round(total_cost_usd / primary_score, 6)
    return metrics
