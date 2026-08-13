"""Deciding whether a session is running, abandoned, or finished.

This is where a real bug lived. Unmerged fragments were read as "live", but a session
killed uncleanly leaves its fragments behind for good, so runs from five days earlier were
still being called live and the stall rule shouted about each of them on every sweep.
"""

from __future__ import annotations

import time
from pathlib import Path

import polars as pl

from nttd.monitor.registry import ABANDONED_SECONDS, SessionRegistry


def _frame() -> pl.DataFrame:
    return pl.DataFrame({"game_date": [1], "snapshot_json": ["{}"]})


def _session(root: Path, name: str, fragments: bool, age_seconds: int = 0) -> str:
    session = root / name
    if fragments:
        target = session / "_fragments" / "snapshots_0000.parquet"
    else:
        target = session / "snapshots.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    _frame().write_parquet(target)
    if age_seconds:
        old = time.time() - age_seconds
        import os

        os.utime(target, (old, old))
    return name


def _state(root: Path, name: str) -> str:
    registry = SessionRegistry(root)
    meta = registry.feed(name).meta()
    return registry.state_of(meta)


# ----------------------------------------------------------------------


def test_a_session_that_just_wrote_is_running(tmp_path: Path) -> None:
    _session(tmp_path, "ses_now", fragments=True)
    assert _state(tmp_path, "ses_now") == "running"


def test_a_session_silent_for_hours_is_abandoned_not_running(tmp_path: Path) -> None:
    """The bug: this used to read as live forever, and trip the stall rule every sweep."""
    _session(tmp_path, "ses_old", fragments=True, age_seconds=ABANDONED_SECONDS + 60)
    assert _state(tmp_path, "ses_old") == "abandoned"


def test_a_session_silent_for_days_is_abandoned(tmp_path: Path) -> None:
    _session(tmp_path, "ses_ancient", fragments=True, age_seconds=460_000)
    assert _state(tmp_path, "ses_ancient") == "abandoned"


def test_a_merged_session_is_finished(tmp_path: Path) -> None:
    _session(tmp_path, "ses_done", fragments=False)
    assert _state(tmp_path, "ses_done") == "finished"


def test_a_session_silent_a_little_while_is_still_running(tmp_path: Path) -> None:
    """A slow step must not be mistaken for a dead process."""
    _session(tmp_path, "ses_slow", fragments=True, age_seconds=600)
    assert _state(tmp_path, "ses_slow") == "running"


def test_an_abandoned_session_cannot_trip_the_stall_rule(tmp_path: Path) -> None:
    """The whole point: the console must stop shouting about last week's sessions."""
    _session(tmp_path, "ses_old", fragments=True, age_seconds=460_000)
    registry = SessionRegistry(tmp_path)
    entry = registry.entry("ses_old")
    assert entry["meta"]["state"] == "abandoned"
    assert entry["meta"]["live"] is False
    assert "stalled" not in [v["rule"] for v in entry["verdicts"]]


def test_entries_skips_a_directory_it_cannot_read(tmp_path: Path) -> None:
    """One broken directory must not blank the page for every other session."""
    _session(tmp_path, "ses_good", fragments=False)
    (tmp_path / "ses_broken").mkdir()
    (tmp_path / "ses_broken" / "snapshots.parquet").write_bytes(b"not parquet")
    names = [e["meta"]["session_id"] for e in SessionRegistry(tmp_path).entries()]
    assert "ses_good" in names


def test_the_listing_is_bounded_and_newest_first(tmp_path: Path) -> None:
    for index in range(5):
        _session(tmp_path, f"ses_{index}", fragments=False, age_seconds=100 * (5 - index))
    ids = SessionRegistry(tmp_path).session_ids(limit=3)
    assert len(ids) == 3
    assert ids[0] == "ses_4"


def test_an_empty_sessions_directory_lists_nothing(tmp_path: Path) -> None:
    assert SessionRegistry(tmp_path).session_ids() == []
    assert SessionRegistry(tmp_path / "missing").entries() == []
