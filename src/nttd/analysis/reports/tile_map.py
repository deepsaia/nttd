"""Tile map report: terrain visualization from tiles.parquet.

Generates a heatmap of tile heights with water/coast overlays,
plus town, industry, and station markers from snapshot data.
Uses the same color palette and marker shapes as the video renderer.
"""

from __future__ import annotations

import json

import plotly.graph_objects as go

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register
from nttd.analysis.reports.terrain_palette import (
    COLOR_AIR,
    COLOR_INDUSTRY,
    COLOR_RAIL,
    COLOR_ROAD,
    COLOR_SHIP,
    COLOR_TOWN,
    STATION_PLOTLY_SYMBOLS,
    TERRAIN_COLORSCALE,
    classify_station_type,
    prepare_terrain_grid,
)

# Tile flags bitmask (from GS get_map_terrain)
_FLAG_WATER = 1
_FLAG_BUILDABLE = 4


def _build_terrain_figure(s: SessionData) -> go.Figure | None:
    """Build a terrain heatmap from tiles.parquet data."""
    result = prepare_terrain_grid(s.tiles)
    if result is None:
        return None

    terrain, max_x, max_y = result

    fig = go.Figure()

    fig.add_trace(go.Heatmap(
        z=terrain,
        colorscale=TERRAIN_COLORSCALE,
        showscale=True,
        colorbar=dict(title="Height", x=1.08, len=0.5, yanchor="top", y=1, thickness=15),
        hovertemplate="x:%{x} y:%{y} h:%{z}<extra></extra>",
    ))

    # Overlay entities from the last snapshot
    if not s.snapshots.empty:
        try:
            last = s.snapshots.sort_values("game_date").iloc[-1]
            snap = json.loads(last["snapshot_json"])
            _add_entity_traces(fig, snap)
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    fig.update_layout(
        title=f"Terrain Map -- {s.name} ({s.model})",
        xaxis=dict(title="X", scaleanchor="y", constrain="domain", autorange="reversed"),
        yaxis=dict(title="Y", autorange="reversed"),
        legend=dict(
            x=0,
            y=-0.15,
            orientation="h",
            xanchor="left",
            yanchor="top",
            font=dict(size=10),
        ),
        width=800,
        height=900,
        margin=dict(b=120),
        template="plotly_white",
    )
    return fig


def _add_entity_traces(fig: go.Figure, snap: dict) -> None:
    """Add town, industry, and station marker traces to the figure."""
    towns = snap.get("towns", [])
    if towns:
        fig.add_trace(go.Scatter(
            x=[t["x"] for t in towns],
            y=[t["y"] for t in towns],
            mode="markers+text",
            marker=dict(size=10, color=COLOR_TOWN[0], symbol="circle"),
            text=[t.get("name", "") for t in towns],
            textposition="top center",
            textfont=dict(size=8, color=COLOR_TOWN[0]),
            name="Towns",
            hovertemplate="%{text}<br>pop: %{customdata}<extra></extra>",
            customdata=[t.get("population", 0) for t in towns],
        ))

    industries = snap.get("industries", [])
    if industries:
        fig.add_trace(go.Scatter(
            x=[i["x"] for i in industries],
            y=[i["y"] for i in industries],
            mode="markers",
            marker=dict(size=7, color=COLOR_INDUSTRY[0], symbol="diamond"),
            name="Industries",
            hovertemplate="%{customdata}<extra></extra>",
            customdata=[i.get("name", "") for i in industries],
        ))

    # Group stations by transport type for distinct markers
    stations = snap.get("stations", [])
    if stations:
        _add_station_traces(fig, stations)


def _add_station_traces(fig: go.Figure, stations: list[dict]) -> None:
    """Add station traces grouped by transport type with matching shapes."""
    type_colors = {
        "rail": COLOR_RAIL,
        "road": COLOR_ROAD,
        "air": COLOR_AIR,
        "water": COLOR_SHIP,
    }
    grouped: dict[str, list[dict]] = {}
    for st in stations:
        if "x" not in st or "y" not in st:
            continue
        stype = classify_station_type(st)
        grouped.setdefault(stype, []).append(st)

    for stype, group in grouped.items():
        color_hex = type_colors.get(stype, COLOR_ROAD)[0]
        symbol = STATION_PLOTLY_SYMBOLS.get(stype, "diamond")
        label = f"{stype.capitalize()} Stations"
        fig.add_trace(go.Scatter(
            x=[st["x"] for st in group],
            y=[st["y"] for st in group],
            mode="markers",
            marker=dict(size=8, color=color_hex, symbol=symbol),
            name=label,
            hovertemplate="%{customdata}<extra></extra>",
            customdata=[st.get("name", "") for st in group],
        ))


@register("tile_map")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce terrain map visualizations from tile data."""
    data: dict = {"maps": []}
    md_lines: list[str] = ["# Terrain Map\n"]
    figures: list[tuple[str, go.Figure]] = []

    for s in sessions:
        if s.tiles.empty:
            md_lines.append(f"## {s.session_id} ({s.model})")
            md_lines.append("- No tile data available\n")
            data["maps"].append({
                "session_id": s.session_id,
                "has_data": False,
            })
            continue

        tiles = s.tiles
        max_x = int(tiles["x"].max())
        max_y = int(tiles["y"].max())
        total_tiles = len(tiles)
        water_count = int((tiles["flags"].astype(int) & _FLAG_WATER).astype(bool).sum())
        buildable_count = int((tiles["flags"].astype(int) & _FLAG_BUILDABLE).astype(bool).sum())

        map_data = {
            "session_id": s.session_id,
            "has_data": True,
            "map_size": f"{max_x}x{max_y}",
            "total_tiles": total_tiles,
            "water_tiles": water_count,
            "buildable_tiles": buildable_count,
            "water_pct": round(water_count / total_tiles * 100, 1) if total_tiles else 0,
            "height_min": int(tiles["height"].min()),
            "height_max": int(tiles["height"].max()),
            "height_mean": round(float(tiles["height"].mean()), 1),
        }
        data["maps"].append(map_data)

        md_lines.append(f"## {s.session_id} ({s.model})")
        md_lines.append(f"- **Map size**: {map_data['map_size']}")
        md_lines.append(f"- **Total tiles**: {map_data['total_tiles']:,}")
        md_lines.append(f"- **Water**: {map_data['water_tiles']:,} ({map_data['water_pct']}%)")
        md_lines.append(f"- **Buildable**: {map_data['buildable_tiles']:,}")
        h_min, h_max, h_avg = map_data["height_min"], map_data["height_max"], map_data["height_mean"]
        md_lines.append(f"- **Height**: {h_min}-{h_max} (avg {h_avg})")
        md_lines.append("")

        fig = _build_terrain_figure(s)
        if fig is not None:
            figures.append((f"terrain_{s.session_id}", fig))

    return ReportResult(
        name="tile_map",
        title="Terrain Map",
        data=data,
        figures=figures,
        markdown="\n".join(md_lines),
    )
