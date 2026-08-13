"""Reading a session's history, whether it is running or finished.

The failure this guards against has already happened once. A summary read only
``_fragments/`` and reported four runs as zero actions and zero stations, minutes after
the same code had read 2 actions and 2 stations from the same sessions. The sessions had
simply ended, and the fragments had been merged away.

Reading nothing looks exactly like a session that did nothing, which is why it has to be
tested from both layouts rather than checked by eye.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from nttd.analysis.loader import load_session
from nttd.monitor.session_feed import SessionFeed


def _snapshot(date: int, stations: int, vehicles: int, rating: int) -> dict[str, Any]:
    return {
        "game": {"game_date": date, "mode": "stepped", "map_width": 256, "map_height": 256},
        "companies": [{
            "id": 0, "money": 90_000, "loan": 100_000, "value": 5_000, "income": 0,
            "profit_last_year": 0, "performance_rating": rating,
        }],
        "infrastructure": [{
            "company_id": 0, "rail_pieces": 6, "road_pieces": 0, "water_pieces": 0,
            "station_pieces": stations * 3, "airport_pieces": 0,
        }],
        "stations": [
            {"id": i, "name": f"Station {i}", "company_id": 0, "x": 10 + i, "y": 20 + i,
             "has_rail": True, "cargo_waiting": [{"cargo_label": "PASS", "waiting": 40}]}
            for i in range(stations)
        ],
        "vehicles": [
            {"id": i, "type": "rail", "x": 11, "y": 21} for i in range(vehicles)
        ],
        "towns": [{"id": 0, "name": "Mennbury", "population": 500, "x": 12, "y": 22}],
        "industries": [
            {"id": 0, "name": "Coal Mine", "type_name": "Coal Mine", "x": 30, "y": 40,
             "is_raw": True},
        ],
    }


def _snapshot_frame() -> pl.DataFrame:
    rows = [
        _snapshot(737_791, 0, 0, 0),
        _snapshot(737_806, 2, 0, 30),
        _snapshot(737_821, 2, 1, 45),
    ]
    return pl.DataFrame({
        "session_id": ["ses_x"] * 3,
        "game_date": [737_791, 737_806, 737_821],
        "num_stations": [0, 2, 2],
        "num_vehicles": [0, 0, 1],
        "snapshot_json": [json.dumps(r) for r in rows],
    })


def _action_frame() -> pl.DataFrame:
    return pl.DataFrame({
        "game_date": [737_806, 737_806, 737_821],
        "action_type": ["build_rail_station", "build_rail_station", "get_hangars"],
        "status": ["success", "success", "rejected"],
        "error": ["", "", "Unknown action_type: get_hangars"],
    })


def _write_merged(root: Path) -> str:
    session = root / "ses_x"
    session.mkdir(parents=True)
    _snapshot_frame().write_parquet(session / "snapshots.parquet")
    _action_frame().write_parquet(session / "actions.parquet")
    return "ses_x"


def _write_fragments(root: Path) -> str:
    fragments = root / "ses_x" / "_fragments"
    fragments.mkdir(parents=True)
    frame = _snapshot_frame()
    for index in range(len(frame)):
        frame[index].write_parquet(fragments / f"snapshots_{index:04d}.parquet")
    _action_frame().write_parquet(fragments / "actions_0000.parquet")
    return "ses_x"


def _feed(root: Path, session_id: str) -> SessionFeed:
    return SessionFeed(load_session(session_id, sessions_dir=root))


# ----------------------------------------------------------------------


def test_a_finished_session_is_read_from_the_merged_files(tmp_path: Path) -> None:
    feed = _feed(tmp_path, _write_merged(tmp_path))
    assert feed.meta()["steps"] == 3
    assert feed.meta()["stations"] == 2
    assert feed.meta()["vehicles"] == 1


def test_a_running_session_is_read_from_its_fragments(tmp_path: Path) -> None:
    feed = _feed(tmp_path, _write_fragments(tmp_path))
    assert feed.meta()["steps"] == 3
    assert feed.meta()["stations"] == 2
    assert feed.meta()["live"] is True


def test_both_layouts_report_the_same_thing(tmp_path: Path) -> None:
    """The moment a run ends must not change what the monitor says about it."""
    merged = _feed(tmp_path / "a", _write_merged(tmp_path / "a")).meta()
    fragments = _feed(tmp_path / "b", _write_fragments(tmp_path / "b")).meta()
    for key in ("steps", "stations", "vehicles", "rating", "actions", "refused"):
        assert merged[key] == fragments[key], key


def test_the_rating_comes_from_the_newest_snapshot(tmp_path: Path) -> None:
    feed = _feed(tmp_path, _write_merged(tmp_path))
    assert feed.meta()["rating"] == 45


def test_steps_carry_one_row_per_snapshot_in_order(tmp_path: Path) -> None:
    steps = _feed(tmp_path, _write_merged(tmp_path)).steps()
    assert [row["step"] for row in steps] == [0, 1, 2]
    assert [row["game_date"] for row in steps] == [737_791, 737_806, 737_821]
    assert [row["stations"] for row in steps] == [0, 2, 2]


def test_actions_are_counted_against_the_step_that_submitted_them(tmp_path: Path) -> None:
    steps = _feed(tmp_path, _write_merged(tmp_path)).steps()
    assert steps[0]["actions"] == 0
    assert steps[1]["actions"] == 2
    assert steps[1]["refused"] == 0
    assert steps[2]["refused"] == 1


def test_cargo_waiting_is_summed_across_stations(tmp_path: Path) -> None:
    steps = _feed(tmp_path, _write_merged(tmp_path)).steps()
    assert steps[0]["cargo_waiting"] == 0
    assert steps[1]["cargo_waiting"] == 80


def test_infrastructure_is_charted_per_kind(tmp_path: Path) -> None:
    steps = _feed(tmp_path, _write_merged(tmp_path)).steps()
    assert steps[1]["rail_pieces"] == 6
    assert steps[1]["station_pieces"] == 6
    # A kind nothing was built of still gets a labelled zero rather than vanishing.
    assert steps[1]["airport_pieces"] == 0


def test_the_action_mix_separates_successes_from_refusals(tmp_path: Path) -> None:
    mix = _feed(tmp_path, _write_merged(tmp_path)).action_mix()
    assert ("build_rail_station", 2, 0) in mix
    assert ("get_hangars", 0, 1) in mix


def test_the_static_world_carries_towns_and_industries(tmp_path: Path) -> None:
    static = _feed(tmp_path, _write_merged(tmp_path)).static_world()
    assert static["width"] == 256
    assert static["towns"][0]["name"] == "Mennbury"
    assert static["industries"][0]["raw"] is True


def test_the_map_gets_one_frame_per_step(tmp_path: Path) -> None:
    frames = _feed(tmp_path, _write_merged(tmp_path)).dynamic_world()
    assert len(frames) == 3
    assert frames[0]["stations"] == []
    assert len(frames[1]["stations"]) == 2
    assert frames[1]["stations"][0]["kind"] == "rail"
    assert len(frames[2]["vehicles"]) == 1


def test_a_session_with_nothing_recorded_reports_zeros_not_an_error(tmp_path: Path) -> None:
    (tmp_path / "ses_x").mkdir(parents=True)
    feed = _feed(tmp_path, "ses_x")
    assert feed.meta()["steps"] == 0
    assert feed.steps() == []
    assert feed.dynamic_world() == []


def test_an_unreadable_snapshot_row_is_skipped_rather_than_raising(tmp_path: Path) -> None:
    """Fragments are read while another process writes them, so a torn row happens."""
    session = tmp_path / "ses_x"
    session.mkdir(parents=True)
    frame = _snapshot_frame()
    broken = frame.with_columns(
        pl.Series("snapshot_json", [frame["snapshot_json"][0], "{not json", "{}"]),
    )
    broken.write_parquet(session / "snapshots.parquet")
    feed = _feed(tmp_path, "ses_x")
    assert len(feed.steps()) == 2
