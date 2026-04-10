"""Cargo routes report: per-cargo route matrix showing all possible source-dest
pairs grouped by cargo type, with served/unserved status and revenue potential.

Complements cargo_distances (which sorts by distance) by organizing routes
around cargo types and ranking by estimated revenue potential.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import plotly.graph_objects as go

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.cargo_distances import (
    _enrich_water_modes,
    _parse_snapshot_entities,
    _water_tiles_from_parquet,
)
from nttd.analysis.reports.registry import ReportResult, register
from nttd.state.route_planner import RoutePlanner

logger = logging.getLogger(__name__)

# Base payment rates per cargo unit per tile (temperate, approximate).
# Used for revenue potential estimation. Source: OpenTTD cargo payment graph.
_BASE_PAYMENT: dict[str, int] = {
    "COAL": 7,
    "GRAIN": 6,
    "LVST": 5,
    "IORE": 6,
    "STEL": 8,
    "WOOD": 7,
    "GOOD": 10,
    "OIL_": 8,
    "PASS": 5,
    "MAIL": 7,
    "VALU": 15,
}
_DEFAULT_PAYMENT = 6


def _estimate_revenue(cargo: str, monthly_production: int, distance: int) -> int:
    """Rough annual revenue estimate for a cargo route.

    revenue ~ base_payment * monthly_production * distance * 12 months.
    This is a simplified model -- actual revenue depends on transit time
    and the cargo payment curve, but it ranks routes correctly.
    """
    base = _BASE_PAYMENT.get(cargo, _DEFAULT_PAYMENT)
    return base * monthly_production * max(distance, 1) * 12


def _compute_cargo_routes(s: SessionData) -> dict[str, Any]:
    """Compute per-cargo route matrices with revenue potential."""
    if s.snapshots.empty:
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort_values("game_date").iloc[-1]
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    industries, towns, stations, routes = _parse_snapshot_entities(snap)
    planner = RoutePlanner(industries, towns, stations, routes)

    all_routes = planner.cargo_routes()

    # Enrich with tiles.parquet water data
    water_tiles = _water_tiles_from_parquet(s)
    _enrich_water_modes(all_routes, water_tiles)

    # Add revenue estimates
    for r in all_routes:
        r["revenue_potential"] = _estimate_revenue(
            r["cargo"], r["monthly_production"], r["distance"],
        )

    # Group by cargo type
    by_cargo: dict[str, list[dict[str, Any]]] = {}
    for r in all_routes:
        by_cargo.setdefault(r["cargo"], []).append(r)

    # Sort each cargo group by revenue potential descending
    for cargo_routes in by_cargo.values():
        cargo_routes.sort(key=lambda r: r["revenue_potential"], reverse=True)

    # Top routes across all cargoes by revenue potential
    all_by_revenue = sorted(all_routes, key=lambda r: r["revenue_potential"], reverse=True)

    total = len(all_routes)
    served = sum(1 for r in all_routes if r["served"])

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "by_cargo": by_cargo,
        "top_routes": all_by_revenue[:30],
        "summary": {
            "total_routes": total,
            "served_routes": served,
            "unserved_routes": total - served,
            "cargo_types": len(by_cargo),
            "cargo_breakdown": {
                cargo: {
                    "total": len(routes),
                    "served": sum(1 for r in routes if r["served"]),
                }
                for cargo, routes in by_cargo.items()
            },
        },
    }


def _format_markdown(stats: list[dict[str, Any]]) -> str:
    """Render cargo route matrices as markdown."""
    lines: list[str] = ["# Cargo Routes Report\n"]

    for st in stats:
        lines.append(f"## {st['session_id']} ({st['model']})")
        if not st["has_data"]:
            lines.append("- No snapshot data available\n")
            continue

        s = st["summary"]
        lines.append(f"- **Total routes**: {s['total_routes']} "
                      f"({s['served_routes']} served, {s['unserved_routes']} unserved)")
        lines.append(f"- **Cargo types**: {s['cargo_types']}")
        lines.append("")

        # Cargo breakdown summary
        lines.append("### Cargo Type Summary")
        lines.append("| Cargo | Routes | Served | Unserved |")
        lines.append("|-------|-------:|-------:|---------:|")
        for cargo, info in sorted(s["cargo_breakdown"].items()):
            lines.append(
                f"| {cargo} | {info['total']} | {info['served']} "
                f"| {info['total'] - info['served']} |"
            )
        lines.append("")

        # Per-cargo route matrices
        for cargo, routes in sorted(st["by_cargo"].items()):
            src_count = len({r["source_id"] for r in routes})
            dst_count = len({r["dest_id"] for r in routes})
            lines.append(f"### {cargo} ({src_count} sources, {dst_count} destinations)")
            lines.append(
                "| Source | Destination | Distance | Production | Revenue Est. | Modes | Served |"
            )
            lines.append(
                "|--------|-------------|--------:|-----------:|-------------:|-------|:------:|"
            )
            for r in routes:
                modes = ", ".join(r["transport_modes"])
                served = "yes" if r["served"] else ""
                lines.append(
                    f"| {r['source_name']} | {r['dest_name']} "
                    f"| {r['distance']} | {r['monthly_production']} "
                    f"| {r['revenue_potential']:,} | {modes} | {served} |"
                )
            lines.append("")

        # Top routes by revenue potential
        if st["top_routes"]:
            lines.append("### Top 30 Routes by Revenue Potential")
            lines.append(
                "| Rank | Source | Cargo | Destination | Distance | Revenue Est. | Served |"
            )
            lines.append(
                "|-----:|--------|-------|-------------|--------:|-------------:|:------:|"
            )
            for i, r in enumerate(st["top_routes"], 1):
                served = "yes" if r["served"] else ""
                lines.append(
                    f"| {i} | {r['source_name']} | {r['cargo']} | {r['dest_name']} "
                    f"| {r['distance']} | {r['revenue_potential']:,} | {served} |"
                )
            lines.append("")

    return "\n".join(lines)


def _build_figure(stats: list[dict[str, Any]]) -> go.Figure:
    """Build a bar chart of top 20 routes by estimated revenue potential."""
    fig = go.Figure()
    for st in stats:
        if not st.get("has_data"):
            continue
        routes = st["top_routes"][:20]
        if not routes:
            continue

        labels = [f"{r['source_name']} -> {r['dest_name']} ({r['cargo']})" for r in routes]
        revenues = [r["revenue_potential"] for r in routes]
        colors = ["#27ae60" if r["served"] else "#e74c3c" for r in routes]

        fig.add_trace(go.Bar(
            y=labels,
            x=revenues,
            orientation="h",
            marker_color=colors,
            name=st["session_id"],
        ))

    fig.update_layout(
        title="Top Routes by Estimated Annual Revenue (green=served, red=unserved)",
        xaxis_title="Estimated Annual Revenue",
        yaxis={"autorange": "reversed"},
        height=max(400, 20 * 30 + 100),
        showlegend=False,
    )
    return fig


@register("cargo_routes")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce per-cargo route matrix with revenue potential ranking."""
    stats = [_compute_cargo_routes(s) for s in sessions]
    data = {"cargo_routes": stats}
    markdown = _format_markdown(stats)
    figures = [("cargo_revenue_potential", _build_figure(stats))]

    return ReportResult(
        name="cargo_routes",
        title="Cargo Routes Report",
        data=data,
        figures=figures,
        markdown=markdown,
    )
