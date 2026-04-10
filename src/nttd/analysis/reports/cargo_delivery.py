"""Cargo delivery report: cargo delivered, revenue by transport mode."""

from __future__ import annotations

import json

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import transport_mode_finances
from nttd.analysis.reports.registry import ReportResult, register


def _extract_cargo_stats(s: SessionData) -> dict:
    """Extract cargo and vehicle profit stats from snapshot_json."""
    if s.snapshots.empty:
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort_values("game_date").iloc[-1]
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    vehicles = snap.get("vehicles", [])
    # profit_this_year resets to 0 at each game-year boundary;
    # profit_last_year holds the previous completed year's value.
    # "has_year_passed" gates whether we show last_year / total columns.
    type_profit_this_year: dict[str, int] = {}
    type_profit_last_year: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    has_year_passed = False
    for v in vehicles:
        vtype = v.get("type", "unknown")
        p_this = v.get("profit_this_year", 0)
        p_last = v.get("profit_last_year", 0)
        if p_last != 0:
            has_year_passed = True
        type_profit_this_year[vtype] = type_profit_this_year.get(vtype, 0) + p_this
        type_profit_last_year[vtype] = type_profit_last_year.get(vtype, 0) + p_last
        type_counts[vtype] = type_counts.get(vtype, 0) + 1

    total_this = sum(type_profit_this_year.values())
    total_last = sum(type_profit_last_year.values())

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "has_year_passed": has_year_passed,
        "total_vehicles": len(vehicles),
        "profit_this_year": total_this,
        "profit_last_year": total_last,
        "profit_total": total_this + total_last,
        "profit_this_year_by_type": type_profit_this_year,
        "profit_last_year_by_type": type_profit_last_year,
        "vehicles_by_type": type_counts,
    }


@register("cargo_delivery")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce cargo delivery and transport mode revenue analysis."""
    stats = [_extract_cargo_stats(s) for s in sessions]
    data = {"cargo": stats}
    md_lines: list[str] = ["# Cargo & Transport Report\n"]

    for st in stats:
        md_lines.append(f"## {st['session_id']} ({st['model']})")
        if not st["has_data"]:
            md_lines.append("- No vehicle data available\n")
            continue

        md_lines.append(f"- **Total vehicles**: {st['total_vehicles']}")
        md_lines.append(f"- **Profit (this year)**: {st['profit_this_year']:,}")
        if st["has_year_passed"]:
            md_lines.append(f"- **Profit (last year)**: {st['profit_last_year']:,}")
            md_lines.append(f"- **Profit (total)**: {st['profit_total']:,}")
        md_lines.append("- **By transport mode**:")
        all_types = sorted(set(
            list(st["profit_this_year_by_type"].keys()) +
            list(st["profit_last_year_by_type"].keys()),
        ))
        for vtype in all_types:
            count = st["vehicles_by_type"].get(vtype, 0)
            p_this = st["profit_this_year_by_type"].get(vtype, 0)
            if st["has_year_passed"]:
                p_last = st["profit_last_year_by_type"].get(vtype, 0)
                md_lines.append(
                    f"  - {vtype}: {count} vehicles, "
                    f"this year: {p_this:,}, last year: {p_last:,}, total: {p_this + p_last:,}"
                )
            else:
                md_lines.append(f"  - {vtype}: {count} vehicles, {p_this:,} profit")
        md_lines.append("")

    figures = [("transport_finances", transport_mode_finances(sessions))]

    return ReportResult(
        name="cargo_delivery",
        title="Cargo & Transport Report",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
