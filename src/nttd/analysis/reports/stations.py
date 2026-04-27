"""Stations report: cargo waiting, acceptance, and supply at each station."""

from __future__ import annotations

import json

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register, session_header


def _classify_type(st: dict) -> str:
    """Return a human-readable transport type string for a station."""
    parts: list[str] = []
    if st.get("has_rail"):
        parts.append("Rail")
    if st.get("has_bus"):
        parts.append("Bus")
    if st.get("has_truck"):
        parts.append("Truck")
    if st.get("has_airport"):
        parts.append("Airport")
    if st.get("has_dock"):
        parts.append("Dock")
    return ", ".join(parts) or "Unknown"


def _extract_station_data(s: SessionData) -> dict:
    """Extract station cargo data from the latest snapshot."""
    if s.snapshots.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort("game_date").row(-1, named=True)
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    stations = snap.get("stations", [])
    if not stations:
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    station_list: list[dict] = []
    total_waiting = 0
    for st in stations:
        waiting = st.get("cargo_waiting", [])
        acceptance = st.get("cargo_acceptance", [])
        station_total = sum(c.get("waiting", 0) for c in waiting)
        total_waiting += station_total

        waiting_items = [
            {"cargo_label": c.get("cargo_label", ""), "waiting": c.get("waiting", 0)}
            for c in waiting if c.get("waiting", 0) > 0
        ]
        accepts_labels = [
            c.get("cargo_label", "") for c in acceptance if c.get("accepts")
        ]
        produces_labels = [
            c.get("cargo_label", "") for c in acceptance if c.get("produces")
        ]
        supply_items = [
            {"cargo_label": c.get("cargo_label", ""), "supply": c.get("supply", 0)}
            for c in acceptance if c.get("supply", 0) > 0
        ]
        rated_labels = [
            c.get("cargo_label", "") for c in acceptance if c.get("rated")
        ]

        station_list.append({
            "id": st.get("id", 0),
            "name": st.get("name", ""),
            "company_id": st.get("company_id", 0),
            "x": st.get("x", 0),
            "y": st.get("y", 0),
            "transport_type": _classify_type(st),
            "total_waiting": station_total,
            "cargo_waiting": waiting_items,
            "accepts": accepts_labels,
            "produces": produces_labels,
            "supply": supply_items,
            "rated": rated_labels,
        })

    station_list.sort(key=lambda x: x["total_waiting"], reverse=True)

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "num_stations": len(station_list),
        "total_waiting": total_waiting,
        "stations": station_list,
    }


@register("stations")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce a station-level cargo availability and acceptance report."""
    all_data = [_extract_station_data(s) for s in sessions]
    data = {"stations": all_data}
    md_lines: list[str] = ["# Stations Report\n"]

    for s, sd in zip(sessions, all_data):
        md_lines.append(session_header(s))
        if not sd["has_data"]:
            md_lines.append("- No station data available\n")
            continue

        md_lines.append(
            f"- **Stations**: {sd['num_stations']}  "
            f"| **Total cargo waiting**: {sd['total_waiting']:,}"
        )
        md_lines.append("")

        md_lines.append("### Station Overview")
        md_lines.append("| Station | Type | Waiting | Accepts | Produces | Rated |")
        md_lines.append("|---------|------|--------:|---------|----------|-------|")
        for st in sd["stations"]:
            waiting_str = str(st["total_waiting"]) if st["total_waiting"] else "-"
            accepts_str = ", ".join(st["accepts"]) if st["accepts"] else "-"
            produces_str = ", ".join(st["produces"]) if st["produces"] else "-"
            rated_str = ", ".join(st["rated"]) if st["rated"] else "-"
            md_lines.append(
                f"| {st['name']} | {st['transport_type']} | {waiting_str} "
                f"| {accepts_str} | {produces_str} | {rated_str} |"
            )
        md_lines.append("")

        stations_with_cargo = [st for st in sd["stations"] if st["cargo_waiting"]]
        if stations_with_cargo:
            md_lines.append("### Cargo Waiting Breakdown")
            md_lines.append("| Station | Cargo | Waiting |")
            md_lines.append("|---------|-------|--------:|")
            for st in stations_with_cargo:
                for cw in sorted(st["cargo_waiting"], key=lambda x: x["waiting"], reverse=True):
                    md_lines.append(
                        f"| {st['name']} | {cw['cargo_label']} | {cw['waiting']:,} |"
                    )
            md_lines.append("")

        stations_with_supply = [st for st in sd["stations"] if st["supply"]]
        if stations_with_supply:
            md_lines.append("### Cargo Supply")
            md_lines.append("| Station | Cargo | Supply |")
            md_lines.append("|---------|-------|-------:|")
            for st in stations_with_supply:
                for cs in sorted(st["supply"], key=lambda x: x["supply"], reverse=True):
                    md_lines.append(
                        f"| {st['name']} | {cs['cargo_label']} | {cs['supply']:,} |"
                    )
            md_lines.append("")

    return ReportResult(
        name="stations",
        title="Stations Report",
        data=data,
        figures=[],
        markdown="\n".join(md_lines),
    )
