"""The pages: an index of sessions, and one session in detail.

Two levels rather than three. nmaps has runs containing episodes, but an nttd session is
one company playing once, so there is nothing between "all sessions" and "this session".

Both levels are rendered server side and complete. The page auto refreshes only while a
session is still running, so an ended session sits still and can be read.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from nttd.analysis.date_utils import game_date_to_dmy
from nttd.monitor import assets
from nttd.monitor.charts import (
    colour,
    esc,
    kpi_cards,
    line_chart,
    mix_bars,
    number,
    panel,
    table,
)
from nttd.monitor.session_feed import (
    INFRA_KINDS,
    STATION_KINDS,
    VEHICLE_KINDS,
    SessionFeed,
)
from nttd.monitor.worldmap import world_panel

# How often the browser re-requests a page showing a live session. A step takes about a
# minute, so this is frequent enough to see progress and rare enough not to reparse the
# world every few seconds.
LIVE_REFRESH_SECONDS = 5

# The single series charts, as (field, title). Money and counts that only make sense
# against a companion are charted separately below.
_SINGLE_CHARTS = (
    ("rating", "Performance rating (the score)"),
    ("value", "Company value"),
    ("income", "Income (this quarter, resets each quarter)"),
    ("fleet_profit", "Fleet profit this year (live)"),
    ("cargo_waiting", "Cargo waiting at stations"),
)


def _when(game_date: Any) -> str:
    """A game date as 05-Jan-1950, or blank when there is none.

    The tables used to print the raw day count OpenTTD reports, 737792, which no reader can
    place in time. Blank rather than "0" for a missing value, because a date of zero is a claim
    and an absent date is not.
    """
    try:
        return game_date_to_dmy(int(game_date))
    except (TypeError, ValueError):
        return ""


def shell(inner: str, refresh: int = 0) -> str:
    meta_refresh = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">{meta_refresh}'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>nttd monitor</title>"
        f"<script>{assets.THEME_HEAD_JS}</script><style>{assets.CSS}</style></head>"
        f'<body><div class="app">{inner}</div>'
        f"<script>{assets.JS}</script><script>{assets.THEME_BODY_JS}</script>"
        f"<script>{assets.DELETE_BODY_JS}</script></body></html>"
    )


def error_page(message: str) -> str:
    return (
        f'<!doctype html><meta charset="utf-8"><style>{assets.CSS}</style>'
        f'<body><div class="main"><div class="plot"><div class="err">{esc(message)}</div>'
        f"</div></div></body>"
    )


def index_page(entries: list[dict[str, Any]]) -> str:
    """Every session, newest first, with enough to see which one needs attention."""
    body = [_sidebar(entries, None), '<div class="main">']
    if not entries:
        body.append(
            '<div class="ph big">No sessions yet. Start one with '
            "<code>nttd benchmark</code> and it appears here as it steps.</div>"
        )
    else:
        body.append(_index_view(entries))
    body.append("</div>")
    live = any(e["meta"]["live"] for e in entries)
    return shell("".join(body), refresh=LIVE_REFRESH_SECONDS if live else 0)


def session_page(
    entries: list[dict[str, Any]],
    feed: SessionFeed,
    meta: dict[str, Any],
    verdicts: list[dict[str, str]],
    terrain: dict[str, Any] | None = None,
) -> str:
    """One session: headline figures, then charts beside the map, then the logs.

    Three bands rather than one grid.

    The first band is one row: the charts on the left, and at the right edge the map with
    the verdicts directly under it. Those two answer the same question, what this run looks
    like and what is wrong with it, so they stay together in one column and in one glance
    rather than a scroll.

    The two logs sit last, side by side, because they are read against each other: an
    action and the event it caused.
    """
    steps = feed.steps()
    body = [_sidebar(entries, meta["session_id"]), '<div class="main">']
    body.append(_session_header(meta))
    body.append(_session_cards(meta))
    body.append(_meta_strip(meta))

    body.append('<div class="split">')
    body.append('<div class="grid">')
    body.extend(_charts(steps))
    body.append(mix_bars("mix", feed.action_mix(), "Actions attempted, and how they went"))
    body.append("</div>")
    body.append('<div class="rail">')
    body.append(world_panel(feed.static_world(), feed.dynamic_world(), "World", terrain))
    body.append(_health_panel(verdicts))
    body.append("</div></div>")

    body.append('<div class="grid pair">')
    body.append(_action_table(feed))
    body.append(_event_table(feed))
    body.append("</div></div>")
    return shell("".join(body), refresh=LIVE_REFRESH_SECONDS if meta["live"] else 0)


# ----------------------------------------------------------------------


def _sidebar(entries: list[dict[str, Any]], active: str | None) -> str:
    out = [
        '<div class="sidebar">',
        '<div class="sbhead"><h1>nttd monitor</h1>'
        '<button class="themebtn" id="themebtn" aria-label="switch theme" '
        'title="switch theme">' + assets.THEME_ICONS + "</button></div>",
        f'<a class="nav {"on" if active is None else ""}" href="/">'
        f'<span class="ndot all"></span><span class="nname">All sessions</span>'
        f'<span class="ncount">{len(entries)}</span></a>',
        '<div class="navlabel">sessions</div>',
    ]
    for index, entry in enumerate(entries):
        meta = entry["meta"]
        dot = '<span class="livedot" title="running now"></span>' if meta["live"] else ""
        # The delete control is a sibling of the link, not a child: a button inside an anchor
        # is invalid HTML and browsers resolve it by following the link instead. A form with
        # method="post" rather than a link, so no prefetch or crawl can delete a session.
        out.append(
            f'<div class="navrow">'
            f'<a class="nav {"on" if meta["session_id"] == active else ""}" '
            f'href="{_session_link(meta["session_id"])}">'
            f'<span class="ndot" style="background:{colour(index)}"></span>'
            f'<span class="meta"><span class="name">{dot}{esc(meta["name"])}</span>'
            f'<span class="stat">step {meta["steps"]} &middot; rating '
            f'{number(meta["rating"])}</span></span></a>'
            f'{_delete_control(meta)}'
            f'</div>'
        )
    out.append("</div>")
    return "".join(out)


def _index_view(entries: list[dict[str, Any]]) -> str:
    live = sum(1 for e in entries if e["meta"]["live"])
    unwell = sum(1 for e in entries if e["health"]["level"] != "ok")
    cards = kpi_cards([
        ("sessions", len(entries), ""),
        ("running", live, "good" if live else ""),
        ("need attention", unwell, "bad" if unwell else "good"),
    ])
    rows = []
    for entry in entries:
        meta, health = entry["meta"], entry["health"]
        rows.append([
            _state_label(meta),
            meta["name"],
            meta["scenario"] or "-",
            meta["seed"] or "-",
            str(meta["steps"]),
            number(meta["rating"]),
            number(meta["value"]),
            str(meta["stations"]),
            str(meta["vehicles"]),
            f"{meta['actions']} ({meta['refused']} refused)",
            _clock(meta["minutes"]),
            health["summary"],
        ])
    header = (
        '<div class="tabs"><span class="tab on">All sessions</span>'
        '<span class="hint">open one in the sidebar for its charts and map</span></div>'
    )
    listing = table(
        ["state", "name", "scenario", "seed", "steps", "rating", "value", "stations",
         "vehicles", "actions", "wall (hh:mm:ss)", "health"],
        rows,
        "Sessions, newest first",
        "no sessions",
    )
    return header + cards + '<div class="grid">' + listing + "</div>"


def _delete_control(meta: dict[str, Any]) -> str:
    """The hover-revealed delete button for one session.

    A running session gets a disabled control rather than none. Offering nothing looks like a
    rendering gap; saying why it cannot be deleted is the useful answer, and removing the
    directory under a live recorder would leave the server writing to a path that is gone.
    """
    if meta["live"]:
        return ('<span class="delbtn off" title="still running; stop the session first">'
                + assets.TRASH_ICON + "</span>")
    session_id = esc(meta["session_id"])
    name = esc(meta["name"])
    return (
        f'<form class="delform" method="post" action="/delete" '
        f'data-name="{name}">'
        f'<input type="hidden" name="session" value="{session_id}">'
        f'<button class="delbtn" type="submit" title="delete this session from disk" '
        f'aria-label="delete {name}">{assets.TRASH_ICON}</button></form>'
    )


def _session_header(meta: dict[str, Any]) -> str:
    live = '<span class="livedot"></span>' if meta["live"] else ""
    ended = "" if meta["live"] else f" &middot; ended: {esc(meta['end_reason'] or 'no reason recorded')}"
    # What the run was FOR, beside what it is called. A board of near-identical ids says
    # nothing about which one was the rail attempt and which the combined one.
    aim = meta.get("description") or ""
    intent = f'<span class="aim">{esc(aim)}</span>' if aim else ""
    return (
        f'<div class="tabs"><a class="tab" href="/">&lsaquo; all sessions</a>'
        f'<span class="tab on">{live}{esc(meta["name"])}</span>{intent}'
        f'<span class="hint">{esc(meta["session_id"])}{ended}</span></div>'
    )


def _clock(minutes: float | None) -> str:
    """Elapsed wall time as hh:mm:ss.

    Minutes with one decimal was unreadable at the range these runs cover: a T1 run is about
    45 minutes and a T4 is two hours, so "127.4m" needs arithmetic before it means anything.
    """
    total = int(round((minutes or 0) * 60))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _session_cards(meta: dict[str, Any]) -> str:
    """The headline figures, and no verdict.

    There was a "health" card here reading "bad", and the same word in every sidebar row. A
    one word judgement at the top of the page decides for the reader what the numbers mean, and
    it was doing so from rules that are heuristics. The Health panel still lists exactly which
    rule tripped and why, which is the useful form: evidence rather than a grade.
    """
    return kpi_cards([
        ("rating", number(meta["rating"]), "good" if (meta["rating"] or 0) > 30 else "warn"),
        ("company value", number(meta["value"]), ""),
        ("balance", number(meta["balance"]), ""),
        ("stations", meta["stations"], ""),
        ("vehicles", meta["vehicles"], "good" if meta["vehicles"] else "bad"),
        ("steps", meta["steps"], ""),
        ("actions", f"{meta['actions']} / {meta['refused']} refused", ""),
        ("wall time (hh:mm:ss)", _clock(meta["minutes"]), ""),
    ])


def _meta_strip(meta: dict[str, Any]) -> str:
    chips = [
        ("scenario", meta["scenario"]),
        ("seed", meta["seed"]),
        ("map", meta["map"]),
        ("play", meta["mode"]),
        ("model", meta["model"]),
        ("game date", _when(meta["game_date"])),
    ]
    parts = [
        f'<span class="chip">{esc(label)}: {esc(value)}</span>'
        for label, value in chips
        if value not in (None, "")
    ]
    return f'<div class="metastrip">{"".join(parts)}</div>'


def _health_panel(verdicts: list[dict[str, str]]) -> str:
    """The verdicts, kept to one line each.

    The reasoning is on the row's tooltip rather than on the page. It is the part worth
    having and the part worth reading once: printed in full it turned a list of four
    faults into a wall of prose beside the map, and a wall is not read at all.
    """
    if not verdicts:
        return panel("Health", '<div class="ph">Nothing has tripped.</div>')
    rows = ['<div class="health">']
    for verdict in verdicts:
        rows.append(
            f'<div class="hrow {esc(verdict["level"])}" '
            f'title="{esc(verdict["why_it_matters"])}">'
            f'<span class="hrule">{esc(verdict["rule"])}</span>'
            f'<span class="hdetail">{esc(verdict["detail"])}</span></div>'
        )
    rows.append("</div>")
    return panel("Health", "".join(rows))


def _charts(steps: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for index, (field, title) in enumerate(_SINGLE_CHARTS):
        out.append(
            line_chart(f"c{index}", [_series(title, colour(index), steps, field)], title, "v")
        )
    out.append(line_chart(
        "cmoney",
        [_series("balance", colour(0), steps, "balance"),
         _series("loan", colour(5), steps, "loan")],
        "Balance against loan", "v",
    ))
    out.append(line_chart(
        "cbuilt",
        [_series("total", colour(1), steps, "stations"),
         *(_series(kind, colour(2 + index), steps, f"stations_{kind}")
           for index, kind in enumerate(STATION_KINDS))],
        "Stations owned, by kind", "v",
    ))
    out.append(line_chart(
        "cfleet",
        [_series("total", colour(2), steps, "vehicles"),
         *(_series(kind, colour(3 + index), steps, f"vehicles_{kind}")
           for index, kind in enumerate(VEHICLE_KINDS))],
        "Vehicles owned, by type", "v",
    ))
    out.append(line_chart(
        "cinfra",
        [_series(kind, colour(index), steps, f"{kind}_pieces")
         for index, kind in enumerate(INFRA_KINDS)],
        "Infrastructure pieces owned", "v",
    ))
    out.append(line_chart(
        "cacts",
        [_series("submitted", colour(1), steps, "actions"),
         _series("refused", colour(5), steps, "refused")],
        "Actions per step", "v",
    ))
    return out


def _series(
    label: str,
    line_colour: str,
    steps: list[dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    """One chart series, with the plotted field copied to a common key.

    The chart draws one field name across all its series, so putting several different
    fields on one panel means renaming them here. Cheaper than teaching the chart about
    per series field names, and it keeps the chart's own contract to a single field.
    """
    return {
        "label": label,
        "colour": line_colour,
        "rows": [{"step": row["step"], "v": row.get(field)} for row in steps],
    }


def _action_table(feed: SessionFeed) -> str:
    rows = [
        [_when(a.get("game_date")), a.get("action_type") or "",
         a.get("status") or "", (a.get("error") or "")[:90]]
        for a in feed.actions()[:120]
    ]
    return table(
        ["game date", "action", "status", "error"], rows,
        "Actions, newest first", "nothing submitted yet", span="one",
    )


def _event_table(feed: SessionFeed) -> str:
    rows = [
        [_when(e.get("game_date")), e.get("event_type") or "",
         str(e.get("detail") or "")[:90]]
        for e in feed.events()[:120]
    ]
    return table(
        ["game date", "event", "detail"], rows,
        "Game events, newest first", "no events recorded", span="one",
    )


def _state_label(meta: dict[str, Any]) -> str:
    """Running, abandoned, or however it ended.

    Abandoned is its own word on purpose. A session whose fragments were never merged
    looked identical to one still playing, which is how sessions from days earlier kept
    being reported as live.
    """
    state = meta.get("state")
    if state == "running":
        return "running"
    if state == "abandoned":
        return "abandoned"
    return meta.get("status") or "ended"


def _session_link(session_id: str) -> str:
    return "/?" + urlencode([("session", session_id)])
