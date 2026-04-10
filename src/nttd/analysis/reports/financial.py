"""Financial report: company finances over time, balance deltas, loan usage."""

from __future__ import annotations

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import company_finances_timeseries, company_loan_balance
from nttd.analysis.reports.registry import ReportResult, register


def _compute_finance_summary(s: SessionData) -> dict:
    """Extract financial summary from snapshots for a single session."""
    if s.snapshots.empty:
        return {
            "session_id": s.session_id,
            "model": s.model,
            "has_data": False,
        }

    df = s.snapshots.sort_values("game_date")
    first = df.iloc[0]
    last = df.iloc[-1]

    # Infrastructure maintenance costs (from pre-extracted columns)
    infra_costs = {}
    for cost_col, label in [
        ("c0_rail_cost", "rail"),
        ("c0_road_cost", "road"),
        ("c0_water_cost", "water"),
        ("c0_station_cost", "station"),
        ("c0_airport_cost", "airport"),
    ]:
        if cost_col in last.index:
            infra_costs[label] = int(last.get(cost_col, 0))

    # Game-day span gives temporal context independent of wall-clock time.
    first_date = int(first.get("game_date", 0))
    last_date = int(last.get("game_date", 0))
    game_days_elapsed = last_date - first_date

    # c0_income resets to 0 at each game year boundary. Detect whether at
    # least one year has completed by checking if 365+ game days elapsed.
    has_year_passed = game_days_elapsed >= 365
    income_this_year = int(last.get("c0_income", 0))
    peak_income = int(df["c0_income"].max()) if "c0_income" in df.columns else 0

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "has_year_passed": has_year_passed,
        "initial_balance": int(first.get("c0_balance", 0)),
        "final_balance": int(last.get("c0_balance", 0)),
        "balance_delta": int(last.get("c0_balance", 0)) - int(first.get("c0_balance", 0)),
        "income_this_year": income_this_year,
        "peak_income": peak_income,
        "final_company_value": int(last.get("c0_value", 0)),
        "final_loan": int(last.get("c0_loan", 0)),
        "peak_balance": int(df["c0_balance"].max()),
        "min_balance": int(df["c0_balance"].min()),
        "game_days_elapsed": game_days_elapsed,
        "infrastructure_costs": infra_costs,
    }


@register("financial")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce company finance timeseries and balance delta analysis."""
    summaries = [_compute_finance_summary(s) for s in sessions]
    data = {"companies": summaries}
    md_lines: list[str] = ["# Financial Report\n"]

    for summary in summaries:
        if not summary["has_data"]:
            md_lines.append(f"## {summary['session_id']} ({summary['model']})")
            md_lines.append("- No snapshot data available\n")
            continue

        md_lines.append(f"## {summary['session_id']} ({summary['model']})")
        md_lines.append(f"- **Game days elapsed**: {summary['game_days_elapsed']}")
        md_lines.append(f"- **Balance**: {summary['initial_balance']:,} -> {summary['final_balance']:,} (cumulative delta: {summary['balance_delta']:+,})")
        md_lines.append(f"- **Peak balance**: {summary['peak_balance']:,}")
        md_lines.append(f"- **Min balance**: {summary['min_balance']:,}")
        md_lines.append(f"- **Income (this year)**: {summary['income_this_year']:,}")
        if summary["has_year_passed"]:
            md_lines.append(f"- **Peak income (best year)**: {summary['peak_income']:,}")
        md_lines.append(f"- **Company value**: {summary['final_company_value']:,}")
        md_lines.append(f"- **Loan outstanding**: {summary['final_loan']:,}")
        if summary.get("infrastructure_costs"):
            md_lines.append("- **Infrastructure costs**:")
            for label, cost in summary["infrastructure_costs"].items():
                if cost > 0:
                    md_lines.append(f"  - {label}: {cost:,}")
        md_lines.append("")

    figures = [
        ("finances_timeseries", company_finances_timeseries(sessions)),
        ("balance_vs_loan", company_loan_balance(sessions)),
    ]

    return ReportResult(
        name="financial",
        title="Financial Report",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
