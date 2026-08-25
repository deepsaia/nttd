"""Inline SVG charts, built on the server.

No charting library and no CDN. The page is finished HTML by the time it reaches the
browser, so it renders with JavaScript off; the small script layer only adds a crosshair
readout and a legend toggle on top of a picture that is already correct.

The alternative was to serve the existing plotly reports, which would mean a figure build
and a JSON payload per panel per refresh, for charts that are a dozen points long. A
polyline is the right size of tool for 31 points.
"""

from __future__ import annotations

import html
import json
from typing import Any

from nttd.monitor.scale import Scale

WIDTH = 460
HEIGHT = 200
PAD_LEFT = 54
PAD_RIGHT = 14
PAD_TOP = 12
PAD_BOTTOM = 26

# Readable on both the light and the dark panel, and distinguishable without relying on
# hue alone being perceived, since these also carry a label in every legend.
PALETTE = (
    "#4f8cff", "#35d0a5", "#ff8a5c", "#c77dff", "#ffd166",
    "#ef476f", "#06d6a0", "#8d99ae", "#f78c6b", "#7bdff2",
)


def colour(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def number(value: Any) -> str:
    """A figure sized for a card or an axis label."""
    if value is None:
        return "-"
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return esc(value)
    if abs(as_float) >= 1e6:
        return f"{as_float / 1e6:,.2f}M"
    if abs(as_float) >= 1e4:
        return f"{as_float / 1e3:,.1f}k"
    if abs(as_float) < 1 and as_float != 0:
        return f"{as_float:,.3f}"
    return f"{as_float:,.0f}"


def money(value: Any) -> str:
    """A sum of money short enough for a sidebar line.

    Separate from `number` rather than a flag on it, because the two round differently and for
    different reasons. `number` labels an axis, where 250.0k and 250k are equally readable. This
    labels a company's worth beside a day and a rating in about twenty characters, so it takes
    the shortest form that still distinguishes two companies: $1.54M, $250K, $812.

    Thousands are whole. A company worth 250,400 and one worth 250,000 are the same company for
    the purpose of a glance, and $250.4K spends a character on a distinction nobody reads there.
    Millions keep two decimals, because at that size the third digit IS the difference between
    two runs.

    The sign goes outside the currency, -$4K rather than $-4K, which is how a negative balance
    is written and, more usefully, how it is scanned: the minus is the first thing seen.
    """
    if value is None:
        return "-"
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return esc(value)

    sign = "-" if as_float < 0 else ""
    size = abs(as_float)

    # Compared against the figure that would ROUND UP into the next tier, not against the tier
    # itself. 999,999 divided by a thousand and rounded to no decimals is 1,000, so a plain
    # `>= 1e6` test prints $1,000K: a thousand thousands, which makes the reader do exactly the
    # arithmetic the shortening was supposed to save. The same boundary exists one tier up,
    # where two decimals mean anything from 999,995,000 rounds to 1,000.00M.
    if size >= 999_995_000:
        return f"{sign}${size / 1e9:,.2f}B"
    if size >= 999_500:
        return f"{sign}${size / 1e6:,.2f}M"
    if size >= 1e3:
        return f"{sign}${size / 1e3:,.0f}K"
    return f"{sign}${size:,.0f}"


def panel(
    title: str,
    inner: str,
    cid: str = "",
    data: str = "",
    span: str = "one",
    expandable: bool = False,
) -> str:
    """One titled panel. ``span`` is how many grid columns it takes: one, two or full.

    A named span rather than a boolean because there are three real cases and the third
    is not "more wide": a table of twelve columns must have the whole row or its last
    columns are simply cut off, which is what happened to the health column.

    ``expandable`` adds a toggle to the title bar. The panel then has two sizes and the grid
    reflows around it, which is what the map needs: one column is enough to see that a route
    exists and too small to see where it goes.
    """
    geom = f' data-geom="{data}"' if data else ""
    css = "plot" if span == "one" else f"plot {span}"
    # Unicode rather than an icon font, so the control survives with no network and no assets.
    toggle = (
        f'<button class="pexp" type="button" data-expand="{esc(cid)}" '
        f'title="Expand or collapse" aria-label="Expand or collapse">\u2922</button>'
        if expandable else ""
    )
    return (
        f'<div class="{css}" data-cid="{esc(cid)}"{geom}>'
        f'<div class="ptitle">{esc(title)}'
        f'<span class="readout" id="ro-{esc(cid)}"></span>{toggle}</div>{inner}</div>'
    )


def line_chart(
    cid: str,
    series: list[dict[str, Any]],
    title: str,
    field: str,
    filled: bool = False,
    marks: list[float] | None = None,
) -> str:
    """One panel plotting ``field`` for each series against its day.

    ``series`` entries are ``{label, colour, rows}``. A point is plotted only when both
    the day and the value are numbers, so a missing figure leaves a gap rather than
    being drawn as a zero, which would read as a real collapse.

    ``marks`` draws a dotted vertical rule at each x. Used for the days a turn ended on:
    the spend line is flat between turns and steps up at one, and the rules say where the
    steps are without a reader having to infer them from the corners.
    """
    points = _collect(series, field)
    if not points:
        return panel(title, '<div class="ph">no data</div>', cid=cid)

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    scale = Scale(
        x_min=min(xs), x_max=max(xs),
        y_min=min(ys + [0]), y_max=max(ys),
        width=WIDTH, height=HEIGHT,
        pad_left=PAD_LEFT, pad_right=PAD_RIGHT,
        pad_top=PAD_TOP, pad_bottom=PAD_BOTTOM,
        integral=all(float(y).is_integer() for y in ys),
    )

    out = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" preserveAspectRatio="none" '
        f'class="chart" data-cid="{esc(cid)}" role="img">'
    ]
    out.extend(_grid(scale))
    out.extend(_marks(scale, marks))
    out.append(
        f'<line class="xhair" x1="0" y1="{PAD_TOP}" x2="0" y2="{HEIGHT - PAD_BOTTOM}" '
        f'stroke-width="1" opacity="0" pointer-events="none"/>'
    )
    embedded: list[dict[str, Any]] = []
    for index, entry in enumerate(series):
        drawn, values = _polyline(entry, field, scale, index, filled=filled)
        out.append(drawn)
        embedded.append({
            "label": entry["label"], "color": entry["colour"], "data": values,
        })
    out.append(
        f'<rect class="hit" x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="transparent"/>'
    )
    out.append("</svg>")

    geom = {
        "xmin": scale.x_min, "xmax": scale.x_max, "padL": PAD_LEFT,
        "padR": PAD_RIGHT, "w": WIDTH, "series": embedded,
    }
    return panel(
        title, "".join(out) + legend(series, cid),
        cid=cid, data=esc(json.dumps(geom)),
    )


def legend(series: list[dict[str, Any]], cid: str) -> str:
    parts = ['<div class="legend">']
    for index, entry in enumerate(series):
        parts.append(
            f'<span class="lg" data-cid="{esc(cid)}" data-si="{index}">'
            f'<span class="sw" style="background:{entry["colour"]}"></span>'
            f'{esc(entry["label"])}</span>'
        )
    parts.append("</div>")
    return "".join(parts)


def kpi_cards(items: list[tuple[str, Any, str]]) -> str:
    """The headline figures. ``items`` are ``(label, value, css class)``."""
    cards = "".join(
        f'<div class="card"><div class="k">{esc(label)}</div>'
        f'<div class="v {css}">{esc(value)}</div></div>'
        for label, value, css in items
    )
    return f'<div class="cards">{cards}</div>'


def mix_bars(cid: str, rows: list[tuple[str, int, int]], title: str) -> str:
    """Per action type, how many succeeded and how many were refused.

    A horizontal split bar rather than a pie or a grouped column: the question is always
    "did this work", and a two colour bar per row answers it without a legend lookup.
    """
    if not rows:
        return panel(title, '<div class="ph">no actions submitted</div>', cid=cid)
    widest = max(ok + bad for _, ok, bad in rows) or 1
    body = ['<div class="mix">']
    for name, ok, bad in rows:
        total = ok + bad
        share = 100.0 * total / widest
        good_share = 100.0 * ok / total if total else 0
        body.append(
            f'<div class="mixrow"><span class="mixlab" title="{esc(name)}">{esc(name)}</span>'
            f'<span class="mixbar" style="flex-basis:{share:.1f}%">'
            f'<span class="seg good" style="flex:0 0 {good_share:.1f}%" '
            f'title="{ok} succeeded"></span>'
            f'<span class="seg bad" style="flex:1 1 auto" title="{bad} refused"></span>'
            f'</span>'
            f'<span class="mixtot">{ok}/{total}</span></div>'
        )
    body.append(
        '<div class="legend"><span class="lg"><span class="sw good"></span>succeeded</span>'
        '<span class="lg"><span class="sw bad"></span>refused</span></div></div>'
    )
    return panel(title, "".join(body), cid=cid)


def table(
    headers: list[str],
    rows: list[list[str]],
    title: str,
    empty: str,
    span: str = "full",
) -> str:
    """A plain table, for the session index, the action log and the event timeline."""
    if not rows:
        return panel(title, f'<div class="ph">{esc(empty)}</div>', span=span)
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return panel(
        title,
        f'<div class="tscroll"><table class="tbl"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        span=span,
    )


# ----------------------------------------------------------------------


# Past this many, one rule per turn is a solid block rather than a reading aid.
_MOST_MARKS = 60


def _collect(series: list[dict[str, Any]], field: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for entry in series:
        for row in entry["rows"]:
            x, y = row.get("day"), row.get(field)
            if _plottable(x) and _plottable(y):
                points.append((float(x), float(y)))
    return points


def _plottable(value: Any) -> bool:
    """Numbers only, and bools are not numbers here.

    ``isinstance(True, int)`` is true in Python, so without this a boolean field would
    silently plot as a zero or one line.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _marks(scale: Scale, marks: list[float] | None) -> list[str]:
    """Dotted verticals at the given x values, inside the plotted range.

    Capped, because a run that reports every day would draw one rule per day and the chart
    would become a solid block. Past the cap the cadence is dense enough to read off the
    line itself, which is the thing the rules exist to make legible.
    """
    if not marks or len(marks) > _MOST_MARKS:
        return []
    out: list[str] = []
    for at in marks:
        if at < scale.x_min or at > scale.x_max:
            continue
        x = scale.x(at)
        out.append(
            f'<line x1="{x:.1f}" y1="{PAD_TOP}" x2="{x:.1f}" y2="{HEIGHT - PAD_BOTTOM}" '
            f'class="mark"/>'
        )
    return out


def _grid(scale: Scale) -> list[str]:
    out: list[str] = []
    for tick in scale.ticks(4):
        if tick < scale.y_min - 1e-9 or tick > scale.y_max + 1e-9:
            continue
        y = scale.y(tick)
        out.append(
            f'<line x1="{PAD_LEFT}" y1="{y:.1f}" x2="{WIDTH - PAD_RIGHT}" y2="{y:.1f}" '
            f'class="gl"/>'
        )
        out.append(
            f'<text x="{PAD_LEFT - 6}" y="{y + 3.5:.1f}" text-anchor="end" class="axl" '
            f'font-size="10">{esc(number(tick))}</text>'
        )
    for tick in (scale.x_min, (scale.x_min + scale.x_max) / 2, scale.x_max):
        out.append(
            f'<text x="{scale.x(tick):.1f}" y="{HEIGHT - PAD_BOTTOM + 15:.1f}" '
            f'text-anchor="middle" class="axl" font-size="10">{int(tick)}</text>'
        )
    return out


def _polyline(
    entry: dict[str, Any],
    field: str,
    scale: Scale,
    index: int,
    filled: bool = False,
) -> tuple[str, list[list[float]]]:
    pixels: list[str] = []
    values: list[list[float]] = []
    for row in entry["rows"]:
        x, y = row.get("day"), row.get(field)
        if not (_plottable(x) and _plottable(y)):
            continue
        pixels.append(f"{scale.x(x):.1f},{scale.y(y):.1f}")
        values.append([float(x), float(y)])
    if len(pixels) >= 2:
        drawn = (
            f'<polyline class="ser s{index}" fill="none" stroke="{entry["colour"]}" '
            f'stroke-width="2" points="{" ".join(pixels)}"/>'
        )
        if filled:
            # Translucent, and drawn UNDER its own line, so overlapping bands stay legible
            # rather than the last one painted hiding the ones before it. Closed down to the
            # baseline at both ends, which is what makes it read as an area rather than a
            # thick line.
            floor = scale.y(scale.y_min)
            first_x = pixels[0].split(",")[0]
            last_x = pixels[-1].split(",")[0]
            area = f"{first_x},{floor:.1f} " + " ".join(pixels) + f" {last_x},{floor:.1f}"
            drawn = (
                f'<polygon class="ser s{index} band" fill="{entry["colour"]}" '
                f'fill-opacity="0.18" stroke="none" points="{area}"/>' + drawn
            )
    elif len(pixels) == 1:
        cx, cy = pixels[0].split(",")
        drawn = (
            f'<circle class="ser s{index}" cx="{cx}" cy="{cy}" r="3" '
            f'fill="{entry["colour"]}"/>'
        )
    else:
        drawn = ""
    return drawn, values
