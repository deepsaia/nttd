"""Live metrics read from a session's parquet files, merged or in fragments."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.analysis.live_metrics import command_rows, finance_rows, iso_date, live_metrics

SESSION = "ses_live"


def write_snapshots(path: Path, rows: list[dict]) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([
        ("game_date", pa.int32()), ("tick", pa.int32()), ("captured_at", pa.timestamp("us")),
        ("c0_balance", pa.int64()), ("c0_loan", pa.int64()), ("c0_value", pa.int64()),
        ("num_vehicles", pa.int16()), ("num_stations", pa.int16()), ("snapshot_json", pa.large_string()),
    ])), path)


def write_actions(path: Path, rows: list[dict]) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([
        ("action_id", pa.string()), ("agent_id", pa.string()), ("game_date", pa.int32()),
        ("action_type", pa.string()), ("status", pa.string()), ("source", pa.string()),
    ])), path)


def snapshot(day: int, tick: int, cash: int, loan: int = 100, value: int = 7, vehicles: int = 1, stations: int = 2) -> dict:
    return {"game_date": day, "tick": tick, "captured_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "c0_balance": cash, "c0_loan": loan, "c0_value": value, "num_vehicles": vehicles,
            "num_stations": stations, "snapshot_json": "{}"}


def action(day: int, agent: str, status: str, source: str = "api") -> dict:
    return {"action_id": f"{agent}:{day}", "agent_id": agent, "game_date": day,
            "action_type": "build_dock", "status": status, "source": source}


def session_dir(tmp_path: Path) -> Path:
    folder = tmp_path / SESSION
    folder.mkdir()
    return folder


def test_iso_date_reads_the_game_calendar() -> None:
    assert iso_date(0) == "0000-01-01"
    assert iso_date(1) == "0000-01-02"
    assert iso_date(366) == "0001-01-01"


def test_finances_keep_the_latest_snapshot_of_each_day_in_day_order(tmp_path: Path) -> None:
    folder = session_dir(tmp_path)
    write_snapshots(folder / "snapshots.parquet", [
        snapshot(715877, 3, 500), snapshot(715876, 1, 1000), snapshot(715876, 2, 900),
    ])
    rows = finance_rows(SESSION, tmp_path)
    assert [row["game_date"] for row in rows] == [715876, 715877]
    assert rows[0]["cash"] == 900 and rows[0]["tick"] == 2
    assert rows[0] == {
        "game_date": 715876, "date": iso_date(715876), "tick": 2, "captured_at": "2026-01-01T00:00:00",
        "cash": 900, "loan": 100, "net_cash": 800, "company_value": 7, "vehicles": 1, "stations": 2,
    }


def test_commands_group_by_day_and_count_actors_and_outcomes(tmp_path: Path) -> None:
    folder = session_dir(tmp_path)
    write_actions(folder / "actions.parquet", [
        action(10, "a", "success"), action(10, "a", "failed"), action(10, "b", "partial"),
        action(10, "b", "rejected"), action(10, "", "blocked"), action(10, "", "odd"),
        action(12, "c", "success"), action(12, "c", "success", source="client"),
    ])
    rows = command_rows(SESSION, tmp_path)
    assert [row["game_date"] for row in rows] == [10, 12]
    assert rows[0] == {"game_date": 10, "date": iso_date(10), "commands": 6, "actors": 3,
                       "successful": 1, "failed": 3, "partial": 1, "unknown": 1}
    assert rows[1]["commands"] == 1 and rows[1]["actors"] == 1


def test_fragments_of_a_running_session_are_read(tmp_path: Path) -> None:
    folder = session_dir(tmp_path)
    fragments = folder / "_fragments"
    fragments.mkdir()
    write_snapshots(fragments / "snapshots_0000.parquet", [snapshot(1, 1, 10)])
    write_snapshots(fragments / "snapshots_0001.parquet", [snapshot(2, 2, 20)])
    write_actions(fragments / "actions_0000.parquet", [action(2, "a", "success")])
    metrics = live_metrics(SESSION, tmp_path)
    assert [row["cash"] for row in metrics["finances"]] == [10, 20]
    assert metrics["commands"][0]["commands"] == 1


def test_a_session_without_files_has_empty_tables(tmp_path: Path) -> None:
    session_dir(tmp_path)
    assert live_metrics(SESSION, tmp_path) == {"finances": [], "commands": []}
