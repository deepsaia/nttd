"""Where session data lives, and that everything reads it the same way.

This bug class has recurred: the sessions directory was resolved independently in
eight places and they disagreed, so `nttd analyze` reported "Session not found" for a
session `nttd result` read fine, and four of the five API repositories silently read
the default directory whatever NTTD_SESSIONS_DIR said. These tests pin the two
invariants that prevent it coming back: one authority for the location, and one read
path that both the API and the analysis loader go through.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nttd.store import parquet_reader, session_paths

SNAPSHOT = {
    "companies": [{"id": 0, "name": "Player", "money": 5000, "loan": 100, "value": 9000}],
    "towns": [{"id": 3, "name": "Testville"}],
    "stations": [{"id": 1, "company_id": 0, "cargo_waiting": [{"cargo": "PASS", "amount": 4}]}],
    "vehicles": [{"id": 2, "company_id": 0, "orders": [{"station_id": 1}]}],
    "industries": [{"id": 5, "production": [{"cargo": "COAL", "amount": 20}]}],
    "subsidies": [{"id": 9}],
}


def _snapshot_table(game_date: int, snapshot: dict[str, Any]) -> pa.Table:
    return pa.table({
        "snapshot_id": [f"snap_{game_date}"],
        "game_date": [game_date],
        "tick": [game_date * 74],
        "captured_at": ["2026-08-05T00:00:00+00:00"],
        "snapshot_json": [json.dumps(snapshot)],
        "c0_balance": [snapshot["companies"][0]["money"]],
        "c0_loan": [snapshot["companies"][0]["loan"]],
        "c0_income": [0],
        "c0_value": [snapshot["companies"][0]["value"]],
        "num_vehicles": [1],
        "num_stations": [1],
        "num_towns": [1],
        "num_companies": [1],
    })


def _actions_table() -> pa.Table:
    return pa.table({
        "action_id": ["act_1"],
        "company_id": [0],
        "agent_id": ["runner"],
        "action_type": ["build_road"],
        "status": ["success"],
        "parameters_json": [json.dumps({"tile": 4242})],
    })


def _events_table() -> pa.Table:
    return pa.table({
        "event_type": ["session_started"],
        "company_id": [0],
        "game_date": [10],
    })


@pytest.fixture
def merged_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A finished session: everything merged into top-level parquet files."""
    monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
    d = tmp_path / "ses_merged"
    d.mkdir()
    pq.write_table(_snapshot_table(10, SNAPSHOT), d / "snapshots.parquet")
    pq.write_table(_actions_table(), d / "actions.parquet")
    pq.write_table(_events_table(), d / "events.parquet")
    return "ses_merged"


@pytest.fixture
def live_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A running session: nothing merged yet, everything still under _fragments/."""
    monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
    frags = tmp_path / "ses_live" / "_fragments"
    frags.mkdir(parents=True)
    pq.write_table(_snapshot_table(10, SNAPSHOT), frags / "snapshots_0001.parquet")
    pq.write_table(_actions_table(), frags / "actions_0001.parquet")
    pq.write_table(_events_table(), frags / "events_0001.parquet")
    return "ses_live"


class TestSessionPaths:
    def test_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(session_paths.ENV_VAR, raising=False)
        assert session_paths.sessions_dir() == Path("logs/sessions")

    def test_honours_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(session_paths.ENV_VAR, "/tmp/somewhere")
        assert session_paths.sessions_dir() == Path("/tmp/somewhere")

    def test_resolved_per_call_not_at_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The import-time constant is what made this hard to configure."""
        monkeypatch.setenv(session_paths.ENV_VAR, "/tmp/first")
        assert session_paths.sessions_dir() == Path("/tmp/first")
        monkeypatch.setenv(session_paths.ENV_VAR, "/tmp/second")
        assert session_paths.sessions_dir() == Path("/tmp/second")

    def test_iter_yields_nothing_when_root_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path / "never_created"))
        assert list(session_paths.iter_session_dirs()) == []

    def test_iter_is_newest_first_and_skips_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
        for name in ("ses_a", "ses_b", "ses_c"):
            (tmp_path / name).mkdir()
        (tmp_path / "stray.txt").write_text("not a session")
        assert [p.name for p in session_paths.iter_session_dirs()] == [
            "ses_c", "ses_b", "ses_a",
        ]


class TestParquetReader:
    def test_reads_merged(self, merged_session: str) -> None:
        table = parquet_reader.read_table(merged_session, "actions")
        assert table is not None
        assert table.num_rows == 1

    def test_falls_back_to_fragments(self, live_session: str) -> None:
        table = parquet_reader.read_table(live_session, "actions")
        assert table is not None
        assert table.num_rows == 1

    def test_none_for_a_type_never_recorded(self, merged_session: str) -> None:
        assert parquet_reader.read_table(merged_session, "tiles") is None

    def test_merged_wins_over_fragments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Once merged, the fragments are stale leftovers and must not double-count."""
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
        d = tmp_path / "ses_both"
        (d / "_fragments").mkdir(parents=True)
        pq.write_table(_actions_table(), d / "_fragments" / "actions_0001.parquet")
        pq.write_table(_actions_table(), d / "actions.parquet")
        table = parquet_reader.read_table("ses_both", "actions")
        assert table is not None
        assert table.num_rows == 1

    def test_explicit_root_overrides_the_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path / "wrong"))
        d = tmp_path / "right" / "ses_x"
        d.mkdir(parents=True)
        pq.write_table(_actions_table(), d / "actions.parquet")
        table = parquet_reader.read_table(
            "ses_x", "actions", sessions_dir=tmp_path / "right",
        )
        assert table is not None
        assert table.num_rows == 1

    def test_snapshot_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
        frags = tmp_path / "ses_many" / "_fragments"
        frags.mkdir(parents=True)
        for date in (10, 20, 30):
            snap = {**SNAPSHOT, "companies": [{"id": 0, "money": date, "loan": 0, "value": 0}]}
            pq.write_table(_snapshot_table(date, snap), frags / f"snapshots_{date}.parquet")

        def money(snapshot: dict[str, Any] | None) -> int:
            assert snapshot is not None
            return snapshot["companies"][0]["money"]

        assert money(parquet_reader.latest_snapshot("ses_many")) == 30
        assert money(parquet_reader.first_snapshot("ses_many")) == 10
        assert money(parquet_reader.snapshot_at("ses_many", 20)) == 20
        # No exact match: the nearest snapshot beats answering with nothing
        assert money(parquet_reader.snapshot_at("ses_many", 22)) == 20

    def test_point_lookups_parse_one_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A point-in-time lookup must not parse the whole series.

        Snapshots hold the full gamestate, so parsing all of them to answer
        "latest towns" costs about 20x more on a long session, per request.
        """
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
        frags = tmp_path / "ses_count" / "_fragments"
        frags.mkdir(parents=True)
        for date in range(12):
            pq.write_table(_snapshot_table(date, SNAPSHOT), frags / f"snapshots_{date:03d}.parquet")

        calls = []
        real_loads = json.loads
        monkeypatch.setattr(
            json, "loads", lambda *a, **kw: (calls.append(1), real_loads(*a, **kw))[1],
        )

        parquet_reader.latest_snapshot("ses_count")
        assert len(calls) == 1

        calls.clear()
        parquet_reader.read_snapshots("ses_count")
        assert len(calls) == 12

    def test_unparseable_snapshot_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(session_paths.ENV_VAR, str(tmp_path))
        frags = tmp_path / "ses_bad" / "_fragments"
        frags.mkdir(parents=True)
        pq.write_table(_snapshot_table(10, SNAPSHOT), frags / "snapshots_010.parquet")
        broken = _snapshot_table(20, SNAPSHOT).set_column(
            _snapshot_table(20, SNAPSHOT).schema.get_field_index("snapshot_json"),
            "snapshot_json",
            pa.array(["{not json"]),
        )
        pq.write_table(broken, frags / "snapshots_020.parquet")

        pairs = parquet_reader.read_snapshots("ses_bad")
        assert [date for date, _ in pairs] == [10]
