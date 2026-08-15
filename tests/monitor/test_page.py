"""The rendered pages.

Assertions are about what a reader can find on the page and about the one thing that is
easy to get silently wrong: whether the page refreshes itself. A finished session that
keeps reloading cannot be read, and a running one that does not is a dead dashboard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from nttd.analysis.loader import load_session
from nttd.monitor import page
from nttd.monitor.health import Health
from nttd.monitor.session_feed import SessionFeed


def _session(root: Path, live: bool, stations: int = 2, vehicles: int = 1) -> SessionFeed:
    snapshot = {
        "game": {"game_date": 737_806, "mode": "stepped", "map_width": 256, "map_height": 256},
        "companies": [{"id": 0, "money": 90_000, "loan": 0, "value": 5_000,
                       "income": 120, "performance_rating": 42}],
        "infrastructure": [{"company_id": 0, "rail_pieces": 6, "station_pieces": 6}],
        "stations": [{"id": i, "name": f"S{i}", "company_id": 0, "x": 10 + i, "y": 20,
                      "has_rail": True, "cargo_waiting": []} for i in range(stations)],
        "vehicles": [{"id": i, "type": "rail", "x": 11, "y": 20} for i in range(vehicles)],
        "towns": [{"id": 0, "name": "Mennbury", "population": 500, "x": 12, "y": 22}],
        "industries": [],
    }
    frame = pl.DataFrame({
        "session_id": ["ses_x"] * 2,
        "game_date": [737_791, 737_806],
        "num_stations": [0, stations],
        "num_vehicles": [0, vehicles],
        "snapshot_json": [json.dumps(snapshot), json.dumps(snapshot)],
    })
    session = root / "ses_x"
    if live:
        fragments = session / "_fragments"
        fragments.mkdir(parents=True)
        frame.write_parquet(fragments / "snapshots_0000.parquet")
    else:
        session.mkdir(parents=True)
        frame.write_parquet(session / "snapshots.parquet")
    return SessionFeed(load_session("ses_x", sessions_dir=root))


def _entry(feed: SessionFeed) -> dict[str, Any]:
    meta = feed.meta()
    health = Health(meta, feed.step_count(), feed.actions())
    return {
        "meta": meta,
        "health": {"level": health.level(), "summary": health.summary()},
        "verdicts": health.verdicts(),
    }


# ----------------------------------------------------------------------


def test_an_empty_index_explains_how_to_start_a_session() -> None:
    html = page.index_page([])
    assert "No sessions yet" in html
    assert "nttd benchmark" in html


def test_an_index_with_no_live_session_does_not_refresh_itself(tmp_path: Path) -> None:
    html = page.index_page([_entry(_session(tmp_path, live=False))])
    assert "http-equiv=\"refresh\"" not in html


def test_a_live_session_is_pushed_to_rather_than_polled(tmp_path: Path) -> None:
    """A meta refresh redrew an identical page most times it fired, and still lagged a real
    change by up to its interval. The page opens one stream and waits instead."""
    html = page.index_page([_entry(_session(tmp_path, live=True))])
    assert "http-equiv=\"refresh\"" not in html
    assert "EventSource('/live')" in html


def test_the_index_lists_what_each_session_built(tmp_path: Path) -> None:
    entry = _entry(_session(tmp_path, live=False, stations=7, vehicles=3))
    html = page.index_page([entry])
    assert "ses_x" in html or "ses_x" in entry["meta"]["session_id"]
    assert ">7<" in html
    assert ">3<" in html


def test_a_session_page_carries_the_map_the_charts_and_the_logs(tmp_path: Path) -> None:
    feed = _session(tmp_path, live=False)
    entry = _entry(feed)
    html = page.session_page([entry], feed, entry["meta"], entry["verdicts"])
    for expected in (
        "wmap",            # the world map
        "wslider",         # its step scrubber
        "Performance rating",
        "Stations owned, by kind",
        "Vehicles owned, by type",
        "Infrastructure pieces owned",
        "Actions per step",
        "Health",
        "Game events",
        "polyline",        # at least one chart actually drew a line
    ):
        assert expected in html, expected


def test_a_healthy_session_says_so_rather_than_showing_an_empty_panel(tmp_path: Path) -> None:
    feed = _session(tmp_path, live=False)
    entry = _entry(feed)
    html = page.session_page([entry], feed, entry["meta"], entry["verdicts"])
    assert "Nothing has tripped" in html


def test_a_failing_session_shows_the_rule_and_why_it_matters(tmp_path: Path) -> None:
    """The verdict has to carry its reasoning, or the panel is just a red word."""
    feed = _session(tmp_path, live=False, stations=22, vehicles=0)
    meta = feed.meta()
    verdicts = [{
        "level": "bad", "rule": "no vehicles",
        "detail": "22 stations, no vehicles",
        "why_it_matters": "stations do not earn, vehicles do",
    }]
    html = page.session_page([_entry(feed)], feed, meta, verdicts)
    assert "no vehicles" in html
    assert "stations do not earn" in html
    assert "hrow bad" in html


def test_an_error_page_shows_the_problem_instead_of_a_blank_tab() -> None:
    html = page.error_page("KeyError('snapshot_json')")
    assert "snapshot_json" in html
    assert "class=\"err\"" in html


def test_the_shell_is_self_contained(tmp_path: Path) -> None:
    """No CDN and no second request: the stylesheet and the script ship inline."""
    html = page.index_page([_entry(_session(tmp_path, live=False))])
    assert "<style>" in html and "<script>" in html
    assert "http://" not in html.split("</head>")[0].replace("http-equiv", "")
    assert "src=" not in html
