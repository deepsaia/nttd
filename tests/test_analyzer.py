"""Tests for the session analyzer system."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nttd.analysis.loader import load_fragments, load_session
from nttd.analysis.reports.registry import (
    ReportResult,
    ensure_reports_loaded,
    list_reports,
    run_reports,
)
from nttd.analysis.reports.renderer import render_all, render_json, render_markdown

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_dir(tmp_path: Path) -> Path:
    """Create a minimal session directory with conf and parquet files."""
    sdir = tmp_path / "ses_test123"
    sdir.mkdir()

    # session.parquet
    from nttd.db.conf_writer import write_session_conf

    write_session_conf(
        sdir,
        session_id="ses_test123",
        name="test-session",
        status="ended",
        created_at="2026-01-01T00:00:00",
        started_at="2026-01-01T00:00:00",
        ended_at="2026-01-01T00:10:00",
        end_reason="time_limit",
        game_port=3979,
        admin_port=3977,
    )


    # actions.parquet
    actions_schema = pa.schema([
        ("action_id", pa.string()),
        ("agent_id", pa.string()),
        ("company_id", pa.int16()),
        ("game_date", pa.int32()),
        ("action_type", pa.string()),
        ("status", pa.string()),
        ("error", pa.string()),
        ("parameters_json", pa.string()),
        ("submitted_at", pa.timestamp("us")),
    ])
    actions = pa.table({
        "action_id": ["a1", "a2", "a3"],
        "agent_id": ["test_agent", "test_agent", "test_agent"],
        "company_id": [0, 0, 0],
        "game_date": [730120, 730121, 730122],
        "action_type": ["connect_road", "buy_vehicle", "add_order"],
        "status": ["success", "success", "failed"],
        "error": ["", "", "ERR_PRECONDITION_FAILED"],
        "parameters_json": ["{}", "{}", "{}"],
        "submitted_at": [None, None, None],
    }, schema=actions_schema)
    pq.write_table(actions, sdir / "actions.parquet")

    # agent_cycles.parquet -- no longer read; kept out of the fixture
    cycles_schema = pa.schema([
        ("connection_id", pa.string()),
        ("cycle_number", pa.int32()),
        ("game_date", pa.int32()),
        ("observe_ms", pa.float32()),
        ("decide_ms", pa.float32()),
        ("execute_ms", pa.float32()),
        ("total_ms", pa.float32()),
        ("actions_proposed", pa.int16()),
        ("actions_executed", pa.int16()),
        ("actions_succeeded", pa.int16()),
        ("actions_failed", pa.int16()),
        ("observation_size_bytes", pa.int32()),
    ])
    cycles = pa.table({
        "connection_id": ["ses:0:test_agent:1", "ses:0:test_agent:1"],
        "cycle_number": [1, 2],
        "game_date": [730120, 730121],
        "observe_ms": [10.0, 12.0],
        "decide_ms": [100.0, 110.0],
        "execute_ms": [50.0, 55.0],
        "total_ms": [160.0, 177.0],
        "actions_proposed": [2, 1],
        "actions_executed": [2, 1],
        "actions_succeeded": [2, 0],
        "actions_failed": [0, 1],
        "observation_size_bytes": [1000, 1200],
    }, schema=cycles_schema)
    pq.write_table(cycles, sdir / "agent_cycles.parquet")

    # events.parquet
    events_schema = pa.schema([
        ("game_date", pa.int32()),
        ("event_type", pa.string()),
        ("company_id", pa.int16()),
        ("detail", pa.string()),
        ("timestamp", pa.timestamp("us")),
    ])
    events = pa.table({
        "game_date": [730120],
        "event_type": ["session_start"],
        "company_id": [0],
        "detail": ["test"],
        "timestamp": [None],
    }, schema=events_schema)
    pq.write_table(events, sdir / "events.parquet")

    # snapshots.parquet (minimal)
    company = {
        "id": 0, "money": 100000, "loan": 300000,
        "income": 5000, "value": 100000,
    }
    town = {
        "id": 0, "name": "Testville", "population": 500,
        "houses": 50, "is_city": False, "growth_rate": 10,
        "x": 64, "y": 64,
    }
    industry = {
        "id": 0, "name": "Test Mine", "type_name": "Coal Mine",
        "is_raw": True, "production": [], "x": 32, "y": 32,
    }
    vehicle = {
        "id": 1, "type": "road", "name": "Bus #1",
        "profit_this_year": 100, "profit_last_year": 0,
        "age": 10, "num_orders": 2,
        "orders": [{"index": 0, "destination": 100, "flags": 0}],
    }
    infra = {
        "company_id": 0, "rail_cost": 0, "road_cost": 100,
        "water_cost": 0, "station_cost": 50, "airport_cost": 0,
    }
    snap_data = {
        "companies": [company],
        "towns": [town],
        "industries": [industry],
        "stations": [{"id": 0, "name": "Testville Station",
                      "company_id": 0, "x": 65, "y": 64}],
        "vehicles": [vehicle],
        "routes": [],
        "subsidies": [],
        "infrastructure": [infra],
        "cargo_flows": [],
    }
    snapshot_schema = pa.schema([
        ("session_id", pa.string()),
        ("snapshot_id", pa.string()),
        ("game_date", pa.int32()),
        ("tick", pa.int32()),
        ("captured_at", pa.timestamp("us")),
        ("snapshot_json", pa.large_string()),
        ("num_companies", pa.int16()),
        ("num_towns", pa.int16()),
        ("num_vehicles", pa.int16()),
        ("num_stations", pa.int16()),
        ("c0_balance", pa.int64()),
        ("c0_loan", pa.int64()),
        ("c0_income", pa.int64()),
        ("c0_value", pa.int64()),
        ("c0_rail_cost", pa.int64()),
        ("c0_road_cost", pa.int64()),
        ("c0_water_cost", pa.int64()),
        ("c0_station_cost", pa.int64()),
        ("c0_airport_cost", pa.int64()),
    ])
    snap = pa.table({
        "session_id": ["ses_test123"],
        "snapshot_id": ["snap_1"],
        "game_date": [730120],
        "tick": [100],
        "captured_at": [None],
        "snapshot_json": [json.dumps(snap_data)],
        "num_companies": [1],
        "num_towns": [1],
        "num_vehicles": [1],
        "num_stations": [1],
        "c0_balance": [100000],
        "c0_loan": [300000],
        "c0_income": [5000],
        "c0_value": [100000],
        "c0_rail_cost": [0],
        "c0_road_cost": [100],
        "c0_water_cost": [0],
        "c0_station_cost": [50],
        "c0_airport_cost": [0],
    }, schema=snapshot_schema)
    pq.write_table(snap, sdir / "snapshots.parquet")

    # tiles.parquet (small 4x4 grid)
    tile_schema = pa.schema([
        ("session_id", pa.string()),
        ("captured_at", pa.timestamp("us")),
        ("x", pa.int16()),
        ("y", pa.int16()),
        ("height", pa.int8()),
        ("slope", pa.int8()),
        ("flags", pa.int8()),
    ])
    tile_rows = []
    for y in range(1, 5):
        for x in range(1, 5):
            tile_rows.append({
                "session_id": "ses_test123",
                "captured_at": None,
                "x": x, "y": y,
                "height": x % 3,
                "slope": 0,
                "flags": 1 if x == 1 else 4,
            })
    tiles = pa.Table.from_pylist(tile_rows, schema=tile_schema)
    pq.write_table(tiles, sdir / "tiles.parquet")

    return sdir


@pytest.fixture()
def fragment_dir(tmp_path: Path) -> Path:
    """Create a session dir with fragment files instead of merged parquet."""
    sdir = tmp_path / "ses_frag"
    fdir = sdir / "_fragments"
    fdir.mkdir(parents=True)

    from nttd.db.conf_writer import write_session_conf

    write_session_conf(sdir, session_id="ses_frag", name="frag-test", status="active")

    schema = pa.schema([
        ("action_id", pa.string()),
        ("agent_id", pa.string()),
        ("company_id", pa.int16()),
        ("game_date", pa.int32()),
        ("action_type", pa.string()),
        ("status", pa.string()),
        ("error", pa.string()),
        ("parameters_json", pa.string()),
        ("submitted_at", pa.timestamp("us")),
    ])

    for i in range(3):
        t = pa.table({
            "action_id": [f"frag_{i}"],
            "agent_id": ["agent_a"],
            "company_id": [0],
            "game_date": [730120 + i],
            "action_type": ["connect_road"],
            "status": ["success"],
            "error": [""],
            "parameters_json": ["{}"],
            "submitted_at": [None],
        }, schema=schema)
        pq.write_table(t, fdir / f"actions_{i:04d}.parquet")

    return sdir


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


class TestLoader:
    def test_load_session(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        assert s.session_id == "ses_test123"
        assert s.name == "test-session"
        assert s.status == "ended"
        assert len(s.actions) == 3
        assert len(s.events) == 1
        assert len(s.snapshots) == 1
        assert len(s.tiles) == 16
        assert not s.is_in_progress

    def test_load_fragments(self, fragment_dir: Path) -> None:
        df = load_fragments(fragment_dir, "actions")
        assert len(df) == 3
        assert list(df["action_id"]) == ["frag_0", "frag_1", "frag_2"]

    def test_load_session_from_fragments(self, fragment_dir: Path) -> None:
        s = load_session("ses_frag", sessions_dir=fragment_dir.parent)
        assert s.name == "frag-test"
        assert len(s.actions) == 3
        assert s.is_in_progress

    def test_load_missing_session_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_session("ses_nonexistent", sessions_dir=tmp_path)


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_reports_registered(self) -> None:
        ensure_reports_loaded()
        reports = list_reports()
        assert len(reports) >= 11
        # agent_performance and token_accounting are gone: both read the
        # gameloop's per-cycle telemetry, which nothing writes since nttd stopped
        # running contestants' agents. Per-model spend now comes from POST /report
        # and lands in result.parquet.
        expected = {
            "session_summary", "financial",
            "cargo_delivery", "vehicle_fleet", "infrastructure",
            "events_timeline", "action_analysis", "world_state",
            "tile_map", "orders",
        }
        assert expected.issubset(set(reports))

    def test_run_all_reports(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s])
        assert len(results) >= 11
        for r in results:
            assert isinstance(r, ReportResult)
            assert r.name
            assert r.title
            assert isinstance(r.data, dict)
            assert isinstance(r.markdown, str)

    def test_run_selected_reports(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["session_summary", "financial"])
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"session_summary", "financial"}

    def test_unknown_report_skipped(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["nonexistent"])
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_render_markdown(self, session_dir: Path, tmp_path: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["session_summary"])
        md_path = render_markdown(results, tmp_path / "out" / "report.md")
        assert md_path.exists()
        content = md_path.read_text()
        assert "Session Summary" in content
        assert "ses_test123" in content

    def test_render_json(self, session_dir: Path, tmp_path: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["session_summary"])
        json_path = render_json(results, tmp_path / "out" / "report.json")
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "reports" in data
        assert data["reports"][0]["name"] == "session_summary"

    def test_render_all(self, session_dir: Path, tmp_path: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["session_summary"])
        out = tmp_path / "full_render"
        written = render_all(results, out, formats=["markdown", "json"])
        assert len(written) == 2
        assert (out / "report.md").exists()
        assert (out / "report.json").exists()


# ---------------------------------------------------------------------------
# Individual report smoke tests
# ---------------------------------------------------------------------------


class TestReportContents:
    def test_session_summary_data(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["session_summary"])
        r = results[0]
        assert r.data["sessions"][0]["name"] == "test-session"
        assert r.data["sessions"][0]["total_actions"] == 3

    def test_financial_data(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["financial"])
        r = results[0]
        company = r.data["companies"][0]
        assert company["has_data"] is True
        assert company["final_balance"] == 100000
        assert company["final_loan"] == 300000
        assert "road" in company["infrastructure_costs"]

    def test_world_state_data(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["world_state"])
        r = results[0]
        world = r.data["world"][0]
        assert world["has_data"] is True
        assert world["num_towns"] == 1
        assert world["towns"][0]["name"] == "Testville"

    def test_tile_map_data(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["tile_map"])
        r = results[0]
        m = r.data["maps"][0]
        assert m["has_data"] is True
        assert m["total_tiles"] == 16
        assert m["water_tiles"] == 4

    def test_action_analysis_data(self, session_dir: Path) -> None:
        s = load_session("ses_test123", sessions_dir=session_dir.parent)
        results = run_reports([s], report_names=["action_analysis"])
        r = results[0]
        stats = r.data["actions"][0]
        assert stats["total_actions"] == 3
        assert stats["successful"] == 2
        assert stats["failed"] == 1
