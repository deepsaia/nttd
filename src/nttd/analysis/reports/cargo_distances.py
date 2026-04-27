"""Cargo distance matrix report: Manhattan distances between producer-consumer
industry pairs and town pairs for route planning analysis.

Manhattan distance is the actual game mechanic for cargo revenue calculation
in OpenTTD, making this matrix directly predictive of route profitability.

Uses the shared RoutePlanner for computation, adding analysis-specific
enrichment (tiles.parquet water detection) and report formatting.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import plotly.graph_objects as go
import polars as pl

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register, session_header
from nttd.schemas.industry import Industry, IndustryAcceptance, IndustryProduction
from nttd.schemas.route import Route
from nttd.schemas.station import Station
from nttd.schemas.town import Town
from nttd.state.route_planner import RoutePlanner, classify_transport_modes

logger = logging.getLogger(__name__)


def _water_tiles_from_parquet(s: SessionData) -> set[tuple[int, int]]:
    """Extract water tile coordinates from tiles.parquet for water proximity."""
    water: set[tuple[int, int]] = set()
    if s.tiles.is_empty() or "flags" not in s.tiles.columns:
        return water
    water_rows = s.tiles.filter((pl.col("flags").cast(pl.Int64) & 1) == 1)
    for row in water_rows.iter_rows(named=True):
        water.add((int(row["x"]), int(row["y"])))
    return water


def _near_water(
    water_tiles: set[tuple[int, int]],
    x: int,
    y: int,
    radius: int = 15,
) -> bool:
    """Check if (x, y) is within radius of any water tile (sampled grid)."""
    if not water_tiles:
        return False
    for dx in range(-radius, radius + 1, 3):
        for dy in range(-radius, radius + 1, 3):
            if (x + dx, y + dy) in water_tiles:
                return True
    return False


def _enrich_water_modes(
    routes: list[dict[str, Any]],
    water_tiles: set[tuple[int, int]],
) -> None:
    """Re-classify transport modes using tiles.parquet water data.

    The RoutePlanner uses dock station proximity as a water proxy, but the
    analysis has access to actual tile data for more accurate classification.
    """
    if not water_tiles:
        return
    for r in routes:
        src_water = _near_water(water_tiles, r.get("source_x", 0), r.get("source_y", 0))
        dst_water = _near_water(water_tiles, r.get("dest_x", 0), r.get("dest_y", 0))
        r["transport_modes"] = classify_transport_modes(
            r["distance"], src_water, dst_water, r["cargo"],
        )


def _enrich_town_water_modes(
    routes: list[dict[str, Any]],
    water_tiles: set[tuple[int, int]],
) -> None:
    """Re-classify transport modes for town routes using tiles.parquet water."""
    if not water_tiles:
        return
    for r in routes:
        water_a = _near_water(water_tiles, r.get("town_a_x", 0), r.get("town_a_y", 0))
        water_b = _near_water(water_tiles, r.get("town_b_x", 0), r.get("town_b_y", 0))
        r["transport_modes"] = classify_transport_modes(
            r["distance"], water_a, water_b, "PASS",
        )


def _parse_snapshot_entities(
    snap: dict[str, Any],
) -> tuple[list[Industry], list[Town], list[Station], list[Route]]:
    """Reconstruct typed pydantic models from snapshot JSON dict."""
    industries = [
        Industry(
            id=ind.get("id", 0),
            name=ind.get("name", ""),
            type_id=ind.get("type_id", 0),
            type_name=ind.get("type_name", ""),
            x=ind.get("x", 0),
            y=ind.get("y", 0),
            is_raw=ind.get("is_raw", False),
            is_processing=ind.get("is_processing", False),
            production=[
                IndustryProduction(
                    cargo_id=p.get("cargo_id", 0),
                    cargo_label=p.get("cargo_label", ""),
                    last_month=p.get("last_month", 0),
                    transported=p.get("transported", 0),
                )
                for p in ind.get("production", [])
            ],
            accepted=[
                IndustryAcceptance(
                    cargo_id=a.get("cargo_id", 0),
                    cargo_label=a.get("cargo_label", ""),
                )
                for a in ind.get("accepted", [])
            ],
        )
        for ind in snap.get("industries", [])
    ]
    towns = [
        Town(
            id=t.get("id", 0),
            name=t.get("name", ""),
            population=t.get("population", 0),
            x=t.get("x", 0),
            y=t.get("y", 0),
        )
        for t in snap.get("towns", [])
    ]
    stations = [
        Station(
            id=st.get("id", 0),
            name=st.get("name", ""),
            x=st.get("x", 0),
            y=st.get("y", 0),
            has_dock=st.get("has_dock", False),
        )
        for st in snap.get("stations", [])
    ]
    routes = [
        Route(
            route_id=r.get("route_id", ""),
            company_id=r.get("company_id", 0),
            vehicle_type=r.get("vehicle_type", ""),
            station_ids=r.get("station_ids", []),
            vehicle_count=r.get("vehicle_count", 0),
            total_profit_this_year=r.get("total_profit_this_year", 0),
            total_profit_last_year=r.get("total_profit_last_year", 0),
        )
        for r in snap.get("routes", [])
    ]
    return industries, towns, stations, routes


def _compute_distances(s: SessionData) -> dict[str, Any]:
    """Compute cargo chain distances and town pair distances."""
    if s.snapshots.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort("game_date").row(-1, named=True)
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    industries, towns, stations, routes = _parse_snapshot_entities(snap)
    planner = RoutePlanner(industries, towns, stations, routes)

    cargo_chain_routes = planner.cargo_routes()
    town_routes = planner.town_routes()

    # Enrich with tiles.parquet water data (more accurate than dock proximity)
    water_tiles = _water_tiles_from_parquet(s)
    _enrich_water_modes(cargo_chain_routes, water_tiles)
    _enrich_town_water_modes(town_routes, water_tiles)

    total_cargo = len(cargo_chain_routes)
    served_cargo = sum(1 for r in cargo_chain_routes if r["served"])
    total_town = len(town_routes)
    served_town = sum(1 for r in town_routes if r["served"])

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "cargo_chain_routes": cargo_chain_routes,
        "town_routes": town_routes,
        "summary": {
            "total_cargo_routes": total_cargo,
            "served_cargo_routes": served_cargo,
            "unserved_cargo_routes": total_cargo - served_cargo,
            "total_town_routes": total_town,
            "served_town_routes": served_town,
            "avg_cargo_distance": (
                round(sum(r["distance"] for r in cargo_chain_routes) / total_cargo, 1)
                if total_cargo > 0 else 0
            ),
            "avg_town_distance": (
                round(sum(r["distance"] for r in town_routes) / total_town, 1)
                if total_town > 0 else 0
            ),
        },
    }


def _format_markdown(
    stats: list[dict[str, Any]],
    sessions: list[SessionData],
) -> str:
    """Render cargo distance data as markdown."""
    lines: list[str] = ["# Cargo Distances Report\n"]

    for s, st in zip(sessions, stats):
        lines.append(session_header(s))
        if not st["has_data"]:
            lines.append("- No snapshot data available\n")
            continue

        s = st["summary"]
        lines.append(f"- **Cargo routes**: {s['total_cargo_routes']} "
                      f"({s['served_cargo_routes']} served, "
                      f"{s['unserved_cargo_routes']} unserved)")
        lines.append(f"- **Town routes**: {s['total_town_routes']} "
                      f"({s['served_town_routes']} served)")
        lines.append(f"- **Avg cargo route distance**: {s['avg_cargo_distance']} tiles")
        lines.append(f"- **Avg town route distance**: {s['avg_town_distance']} tiles")

        if st["cargo_chain_routes"]:
            lines.append("\n### Industry Cargo Routes (sorted by distance)")
            lines.append(
                "| Source | Cargo | Destination | Distance | Production | Modes | Served |"
            )
            lines.append(
                "|--------|-------|-------------|--------:|-----------:|-------|:------:|"
            )
            for r in st["cargo_chain_routes"]:
                modes = ", ".join(r["transport_modes"])
                served = "yes" if r["served"] else ""
                lines.append(
                    f"| {r['source_name']} | {r['cargo']} | {r['dest_name']} "
                    f"| {r['distance']} | {r['monthly_production']} | {modes} | {served} |"
                )

        if st["town_routes"]:
            lines.append("\n### Town Passenger Routes (top 30 by demand)")
            lines.append(
                "| Town A | Town B | Distance | Pop A | Pop B | Demand | Modes | Served |"
            )
            lines.append(
                "|--------|--------|--------:|------:|------:|-------:|-------|:------:|"
            )
            for r in st["town_routes"][:30]:
                modes = ", ".join(r["transport_modes"])
                served = "yes" if r["served"] else ""
                lines.append(
                    f"| {r['town_a_name']} | {r['town_b_name']} "
                    f"| {r['distance']} | {r['town_a_pop']:,} | {r['town_b_pop']:,} "
                    f"| {r['demand_score']:,} | {modes} | {served} |"
                )

        lines.append("")

    return "\n".join(lines)


def _build_figure(stats: list[dict[str, Any]]) -> go.Figure:
    """Build a bar chart of top cargo routes by distance."""
    fig = go.Figure()
    for st in stats:
        if not st.get("has_data"):
            continue
        routes = st["cargo_chain_routes"][:20]
        if not routes:
            continue

        labels = [f"{r['source_name']} -> {r['dest_name']}" for r in routes]
        distances = [r["distance"] for r in routes]
        colors = ["#27ae60" if r["served"] else "#e74c3c" for r in routes]
        cargos = [r["cargo"] for r in routes]

        fig.add_trace(go.Bar(
            y=labels,
            x=distances,
            orientation="h",
            marker_color=colors,
            text=cargos,
            textposition="inside",
            name=st["session_id"],
        ))

    fig.update_layout(
        title="Industry Cargo Routes by Manhattan Distance",
        xaxis_title="Manhattan Distance (tiles)",
        yaxis={"autorange": "reversed"},
        height=max(400, len(stats[0].get("cargo_chain_routes", [])[:20]) * 30 + 100)
        if stats and stats[0].get("has_data") else 400,
        showlegend=False,
    )
    return fig


@register("cargo_distances")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce cargo chain distance matrix and town pair distances."""
    stats = [_compute_distances(s) for s in sessions]
    data = {"cargo_distances": stats}
    markdown = _format_markdown(stats, sessions)
    figures = [("cargo_route_distances", _build_figure(stats))]

    return ReportResult(
        name="cargo_distances",
        title="Cargo Distances Report",
        data=data,
        figures=figures,
        markdown=markdown,
    )
