"""Cargo delivery report: cargo quantities, revenue, and flow analysis."""

from __future__ import annotations

import json

from nttd.analysis.loader import SessionData
from nttd.analysis.plots import transport_mode_finances
from nttd.analysis.reports.registry import ReportResult, register, session_header


def _extract_cargo_stats(s: SessionData) -> dict:
    """Extract cargo quantities, station waiting, cargo flows, and vehicle profits."""
    if s.snapshots.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort("game_date").row(-1, named=True)
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    vehicles = snap.get("vehicles", [])
    stations = snap.get("stations", [])
    cargo_flows = snap.get("cargo_flows", [])

    type_profit_this_year: dict[str, int] = {}
    type_profit_last_year: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    has_year_passed = False
    vehicle_details: list[dict] = []
    for v in vehicles:
        vtype = v.get("type", "unknown")
        p_this = v.get("profit_this_year", 0)
        p_last = v.get("profit_last_year", 0)
        if p_last != 0:
            has_year_passed = True
        type_profit_this_year[vtype] = type_profit_this_year.get(vtype, 0) + p_this
        type_profit_last_year[vtype] = type_profit_last_year.get(vtype, 0) + p_last
        type_counts[vtype] = type_counts.get(vtype, 0) + 1
        vehicle_details.append({
            "id": v.get("id", 0),
            "name": v.get("name", ""),
            "type": vtype,
            "profit_this_year": p_this,
            "profit_last_year": p_last,
            "age": v.get("age", 0),
            "current_speed": v.get("current_speed", 0),
            "running": v.get("running", False),
            "in_depot": v.get("in_depot", False),
            "order_count": v.get("order_count", 0),
        })

    station_cargo: list[dict] = []
    for st in stations:
        waiting_items = st.get("cargo_waiting", [])
        total_waiting = sum(c.get("waiting", 0) for c in waiting_items)
        if total_waiting > 0 or waiting_items:
            station_cargo.append({
                "id": st.get("id", 0),
                "name": st.get("name", ""),
                "cargo_waiting": [
                    {"cargo_label": c.get("cargo_label", ""), "waiting": c.get("waiting", 0)}
                    for c in waiting_items if c.get("waiting", 0) > 0
                ],
                "total_waiting": total_waiting,
            })

    deliveries: list[dict] = []
    pickups: list[dict] = []
    for f in cargo_flows:
        entry = {
            "cargo_label": f.get("cargo_label", ""),
            "cargo_id": f.get("cargo_id", 0),
            "entity_type": f.get("entity_type", ""),
            "entity_id": f.get("entity_id", 0),
            "entity_name": f.get("entity_name", ""),
            "amount": f.get("amount", 0),
        }
        if f.get("direction") == "delivery":
            deliveries.append(entry)
        elif f.get("direction") == "pickup":
            pickups.append(entry)

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
        "vehicle_details": vehicle_details,
        "station_cargo": station_cargo,
        "deliveries": deliveries,
        "pickups": pickups,
    }


def _format_vehicle_table(details: list[dict], has_year_passed: bool) -> list[str]:
    """Format a markdown table of per-vehicle stats."""
    lines: list[str] = []
    if has_year_passed:
        lines.append("| ID | Name | Type | Speed | Orders | This Year | Last Year | Status |")
        lines.append("|---:|------|------|------:|-------:|----------:|----------:|--------|")
    else:
        lines.append("| ID | Name | Type | Speed | Orders | Profit | Status |")
        lines.append("|---:|------|------|------:|-------:|-------:|--------|")
    for v in sorted(details, key=lambda x: x["id"]):
        status = "Running" if v["running"] else ("In Depot" if v["in_depot"] else "Stopped")
        name = v["name"] or f"Vehicle {v['id']}"
        if has_year_passed:
            lines.append(
                f"| {v['id']} | {name} | {v['type']} | {v['current_speed']} | "
                f"{v['order_count']} | {v['profit_this_year']:,} | "
                f"{v['profit_last_year']:,} | {status} |"
            )
        else:
            lines.append(
                f"| {v['id']} | {name} | {v['type']} | {v['current_speed']} | "
                f"{v['order_count']} | {v['profit_this_year']:,} | {status} |"
            )
    return lines


@register("cargo_delivery")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce cargo delivery, cargo quantity, and transport mode revenue analysis."""
    stats = [_extract_cargo_stats(s) for s in sessions]
    data = {"cargo": stats}
    md_lines: list[str] = ["# Cargo & Transport Report\n"]

    for s, st in zip(sessions, stats):
        md_lines.append(session_header(s))
        if not st["has_data"]:
            md_lines.append("- No vehicle data available\n")
            continue

        md_lines.append("### Revenue Summary")
        md_lines.append(f"- **Total vehicles**: {st['total_vehicles']}")
        md_lines.append(f"- **Profit (this year)**: {st['profit_this_year']:,}")
        if st["has_year_passed"]:
            md_lines.append(f"- **Profit (last year)**: {st['profit_last_year']:,}")
            md_lines.append(f"- **Profit (total)**: {st['profit_total']:,}")
        md_lines.append("- **By transport mode**:")
        all_types = sorted(set(
            list(st["profit_this_year_by_type"].keys())
            + list(st["profit_last_year_by_type"].keys()),
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

        if st["station_cargo"]:
            md_lines.append("### Cargo Waiting at Stations")
            md_lines.append("| Station | Cargo | Waiting |")
            md_lines.append("|---------|-------|--------:|")
            for sc in sorted(st["station_cargo"], key=lambda x: x["total_waiting"], reverse=True):
                if sc["cargo_waiting"]:
                    for cw in sc["cargo_waiting"]:
                        md_lines.append(
                            f"| {sc['name']} | {cw['cargo_label']} | {cw['waiting']:,} |"
                        )
                else:
                    md_lines.append(f"| {sc['name']} | - | 0 |")
            md_lines.append("")

        if st["deliveries"]:
            md_lines.append("### Cargo Delivered")
            md_lines.append("| Cargo | Destination | Type | Amount |")
            md_lines.append("|-------|-------------|------|-------:|")
            for d in sorted(st["deliveries"], key=lambda x: x["amount"], reverse=True):
                dest = d["entity_name"] or f"{d['entity_type']} #{d['entity_id']}"
                md_lines.append(
                    f"| {d['cargo_label']} | {dest} | {d['entity_type']} | {d['amount']:,} |"
                )
            md_lines.append("")

        if st["pickups"]:
            md_lines.append("### Cargo Picked Up")
            md_lines.append("| Cargo | Source | Type | Amount |")
            md_lines.append("|-------|--------|------|-------:|")
            for p in sorted(st["pickups"], key=lambda x: x["amount"], reverse=True):
                src = p["entity_name"] or f"{p['entity_type']} #{p['entity_id']}"
                md_lines.append(
                    f"| {p['cargo_label']} | {src} | {p['entity_type']} | {p['amount']:,} |"
                )
            md_lines.append("")

        if not st["deliveries"] and not st["pickups"]:
            md_lines.append("### Cargo Flows")
            md_lines.append("- No cargo flow data recorded this session\n")

        if st["vehicle_details"]:
            md_lines.append("### Vehicle Details")
            md_lines.extend(_format_vehicle_table(
                st["vehicle_details"], st["has_year_passed"]
            ))
            md_lines.append("")

    figures = [("transport_finances", transport_mode_finances(sessions))]

    return ReportResult(
        name="cargo_delivery",
        title="Cargo & Transport Report",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
