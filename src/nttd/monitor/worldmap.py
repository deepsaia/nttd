"""A top down view of the world at one step, with a scrubber over the whole run.

This is not the game's own rendering and does not try to be. It plots the objects the
snapshot already carries: every town, industry, station and vehicle in ``snapshot_json``
has an ``x`` and a ``y``, so the layout of a run is recoverable from data nttd already
writes, with no screenshot, no tile read and no new capture.

There is deliberately no terrain underneath. The existing tile_map and video reports draw
terrain from ``tiles.parquet``, and no session recorded by the stepped runs has one, so a
terrain layer would either be blank or would need a full map scan at session start. Bare
canvas answers the question this panel is for, which is where a company built and whether
its stations are anywhere near the industries and towns that would have paid it.

Colours come from the shared palette that the offline reports use, so the same station
means the same colour whether it is seen live or in a report generated afterwards.
"""

from __future__ import annotations

import json
from typing import Any

from nttd.analysis.reports.terrain_palette import (
    COLOR_AIR,
    COLOR_INDUSTRY,
    COLOR_RAIL,
    COLOR_ROAD,
    COLOR_SHIP,
    COLOR_TOWN,
)
from nttd.monitor.charts import esc, panel

# The palette entries are (hex, rgb) pairs; the browser wants the hex.
_TOWN = COLOR_TOWN[0]
_INDUSTRY = COLOR_INDUSTRY[0]

# Which colour a station gets, by the transport it serves. Bus and truck share road's
# colour because they share road's infrastructure, and telling them apart matters less
# than seeing at a glance that a corridor is a road corridor.
STATION_COLOURS = {
    "rail": COLOR_RAIL[0],
    "bus": COLOR_ROAD[0],
    "truck": COLOR_ROAD[0],
    "dock": COLOR_SHIP[0],
    "air": COLOR_AIR[0],
    "other": "#8d99ae",
}

VEHICLE_COLOURS = {
    "rail": COLOR_RAIL[0],
    "road": COLOR_ROAD[0],
    "water": COLOR_SHIP[0],
    "air": COLOR_AIR[0],
}

# A town dot spans this many tiles at the smallest population and grows with it. Tuned so
# a 23 town map reads as a map rather than as a field of overlapping blobs.
_TOWN_MIN_RADIUS = 1.6
_TOWN_MAX_RADIUS = 4.2


def world_panel(
    static: dict[str, Any],
    frames: list[dict[str, Any]],
    title: str,
    terrain: dict[str, Any] | None = None,
) -> str:
    """The map panel: terrain, the static world, the company, and a step scrubber."""
    width = static.get("width") or 256
    height = static.get("height") or 256
    if not frames:
        return panel(title, '<div class="ph">no snapshots yet</div>', span="one")

    latest = frames[-1]
    body = [
        f'<svg viewBox="0 0 {width} {height}" class="wmap" role="img" '
        f'preserveAspectRatio="xMidYMid meet">',
        f'<rect x="0" y="0" width="{width}" height="{height}" class="wbg"/>',
        _terrain(terrain),
        _industries(static.get("industries") or []),
        _towns(static.get("towns") or []),
        # Rendered server side so the panel is correct with scripting off; the scrubber
        # replaces this group's contents when it is dragged.
        f'<g class="wlive">{_company(latest)}</g>',
        "</svg>",
    ]
    # The colour maps travel with the data so the palette stays defined in one place.
    # Repeating them in the script layer is how a live view and a report drift apart.
    payload = json.dumps(
        {
            "frames": [_frame_payload(f) for f in frames],
            "station_colours": STATION_COLOURS,
            "vehicle_colours": VEHICLE_COLOURS,
        },
        separators=(",", ":"),
    )
    body.append(_scrubber(frames))
    body.append(f'<div class="wdata" data-frames="{esc(payload)}"></div>')
    return panel(title, "".join(body), cid="wmap", span="one", expandable=True)


def _terrain(terrain: dict[str, Any] | None) -> str:
    """The height and water raster, drawn as one image under everything else.

    Served from its own route rather than inlined as a data URI: the browser then caches
    it across the page's ten second refresh, and the terrain does not change.
    """
    if not terrain:
        return ""
    return (
        f'<image href="{esc(terrain["url"])}" x="{terrain["x"]}" y="{terrain["y"]}" '
        f'width="{terrain["width"]}" height="{terrain["height"]}" '
        f'preserveAspectRatio="none" class="wterrain"/>'
    )


def legend_row() -> str:
    """What the shapes and colours mean, once, under the map."""
    entries = [
        (_TOWN, "circle", "town"),
        (_INDUSTRY, "square", "industry"),
        (STATION_COLOURS["rail"], "square", "rail station"),
        (STATION_COLOURS["bus"], "square", "road stop"),
        (STATION_COLOURS["dock"], "square", "dock"),
        (STATION_COLOURS["air"], "square", "airport"),
    ]
    parts = ['<div class="legend">']
    for hex_colour, shape, label in entries:
        css = "sw round" if shape == "circle" else "sw"
        parts.append(
            f'<span class="lg"><span class="{css}" style="background:{hex_colour}">'
            f'</span>{esc(label)}</span>'
        )
    parts.append("</div>")
    return "".join(parts)


# ----------------------------------------------------------------------


def _industries(industries: list[dict[str, Any]]) -> str:
    out: list[str] = ['<g class="winds">']
    for industry in industries:
        x, y = industry.get("x"), industry.get("y")
        if x is None or y is None:
            continue
        # Raw producers are what a route starts from, so they are the filled ones. Both
        # are opaque enough to read against terrain, which is the whole point of drawing
        # them over it.
        opacity = "1" if industry.get("raw") else "0.6"
        out.append(
            f'<rect x="{x - 1}" y="{y - 1}" width="2.4" height="2.4" '
            f'fill="{_INDUSTRY}" opacity="{opacity}">'
            f"<title>{esc(industry.get('name'))} ({esc(industry.get('type'))})</title>"
            f"</rect>"
        )
    out.append("</g>")
    return "".join(out)


def _towns(towns: list[dict[str, Any]]) -> str:
    populations = [t.get("population") or 0 for t in towns]
    biggest = max(populations) if populations else 0
    out: list[str] = ['<g class="wtowns">']
    for town in towns:
        x, y = town.get("x"), town.get("y")
        if x is None or y is None:
            continue
        out.append(
            f'<circle cx="{x}" cy="{y}" r="{_town_radius(town, biggest):.2f}" '
            f'fill="{_TOWN}" opacity="0.9">'
            f"<title>{esc(town.get('name'))}: {esc(town.get('population'))} people</title>"
            f"</circle>"
        )
    out.append("</g>")
    return "".join(out)


def _town_radius(town: dict[str, Any], biggest: int) -> float:
    population = town.get("population") or 0
    if not biggest:
        return _TOWN_MIN_RADIUS
    share = population / biggest
    return _TOWN_MIN_RADIUS + share * (_TOWN_MAX_RADIUS - _TOWN_MIN_RADIUS)


def _company(frame: dict[str, Any]) -> str:
    """The company's own stations and vehicles at one step."""
    out: list[str] = []
    for station in frame.get("stations") or []:
        x, y = station.get("x"), station.get("y")
        if x is None or y is None:
            continue
        fill = STATION_COLOURS.get(station.get("kind") or "other", STATION_COLOURS["other"])
        waiting = station.get("waiting") or 0
        out.append(
            f'<rect x="{x - 1.5}" y="{y - 1.5}" width="3.4" height="3.4" fill="{fill}" '
            f'stroke="#0f1420" stroke-width="0.4">'
            f"<title>{esc(station.get('name'))} ({esc(station.get('kind'))})"
            f"{f', {waiting} waiting' if waiting else ''}</title></rect>"
        )
    for vehicle in frame.get("vehicles") or []:
        x, y = vehicle.get("x"), vehicle.get("y")
        if x is None or y is None:
            continue
        fill = VEHICLE_COLOURS.get(vehicle.get("type") or "", "#e6ebf5")
        out.append(f'<circle cx="{x}" cy="{y}" r="1.2" fill="{fill}"/>')
    return "".join(out)


def _frame_payload(frame: dict[str, Any]) -> dict[str, Any]:
    """One step, small enough to send 200 of them."""
    return {
        "d": frame.get("game_date"),
        "s": [
            [s.get("x"), s.get("y"), s.get("kind"), s.get("name"), s.get("waiting") or 0]
            for s in (frame.get("stations") or [])
            if s.get("x") is not None and s.get("y") is not None
        ],
        "v": [
            [v.get("x"), v.get("y"), v.get("type")]
            for v in (frame.get("vehicles") or [])
            if v.get("x") is not None and v.get("y") is not None
        ],
    }


def _scrubber(frames: list[dict[str, Any]]) -> str:
    last = len(frames) - 1
    return (
        '<div class="wscrub">'
        '<button type="button" class="wlivebtn on" aria-pressed="true" '
        'title="follow the newest step; click after scrubbing to re-sync">'
        '<span class="livedot"></span>LIVE</button>'
        f'<input type="range" class="wslider" min="0" max="{last}" value="{last}" '
        f'step="1" aria-label="step"/>'
        f'<span class="wstep">step {last + 1}</span></div>'
    ) + legend_row()
