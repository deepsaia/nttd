"""Vehicle fleet report: vehicle roster, profits, type breakdown over time."""

from __future__ import annotations

import json

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import entity_growth_timeseries
from nttd.analysis.reports.registry import ReportResult, register


def _extract_vehicle_roster(s: SessionData) -> dict:
    """Build a vehicle roster from the latest snapshot."""
    if s.snapshots.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort("game_date").row(-1, named=True)
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    vehicles = snap.get("vehicles", [])
    roster: list[dict] = []
    for v in vehicles:
        roster.append({
            "id": v.get("id"),
            "name": v.get("name", ""),
            "type": v.get("type", "unknown"),
            "profit_this_year": v.get("profit_this_year", 0),
            "profit_last_year": v.get("profit_last_year", 0),
            "age": v.get("age", 0),
            "num_orders": v.get("num_orders", 0),
        })

    has_year_passed = any(v["profit_last_year"] != 0 for v in roster)
    roster.sort(key=lambda v: v["profit_this_year"] + v["profit_last_year"], reverse=True)

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "has_year_passed": has_year_passed,
        "total_vehicles": len(roster),
        "vehicles": roster,
    }


@register("vehicle_fleet")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce vehicle fleet roster and growth analysis."""
    rosters = [_extract_vehicle_roster(s) for s in sessions]
    data = {"fleets": rosters}
    md_lines: list[str] = ["# Vehicle Fleet Report\n"]

    for r in rosters:
        md_lines.append(f"## {r['session_id']} ({r['model']})")
        if not r["has_data"]:
            md_lines.append("- No vehicle data available\n")
            continue

        md_lines.append(f"- **Total vehicles**: {r['total_vehicles']}\n")

        if r["vehicles"]:
            if r["has_year_passed"]:
                md_lines.append("| ID | Name | Type | This Year | Last Year | Total | Orders |")
                md_lines.append("|---:|------|------|---------:|---------:|------:|-------:|")
                for v in r["vehicles"]:
                    total = v["profit_this_year"] + v["profit_last_year"]
                    md_lines.append(
                        f"| {v['id']} | {v['name']} | {v['type']} "
                        f"| {v['profit_this_year']:,} | {v['profit_last_year']:,} "
                        f"| {total:,} | {v['num_orders']} |"
                    )
            else:
                md_lines.append("| ID | Name | Type | Profit | Orders |")
                md_lines.append("|---:|------|------|-------:|-------:|")
                for v in r["vehicles"]:
                    md_lines.append(
                        f"| {v['id']} | {v['name']} | {v['type']} "
                        f"| {v['profit_this_year']:,} | {v['num_orders']} |"
                    )
        md_lines.append("")

    figures = [("entity_growth", entity_growth_timeseries(sessions))]

    return ReportResult(
        name="vehicle_fleet",
        title="Vehicle Fleet Report",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
