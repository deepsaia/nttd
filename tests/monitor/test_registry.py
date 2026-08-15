"""Deciding whether a session is running, abandoned, or finished.

This is where a real bug lived. Unmerged fragments were read as "live", but a session
killed uncleanly leaves its fragments behind for good, so runs from five days earlier were
still being called live and the stall rule shouted about each of them on every sweep.
"""

from __future__ import annotations

import os
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


def test_the_index_orders_by_when_a_session_started(tmp_path: Path) -> None:
    """Newest run on top, from the timestamp in its id.

    The index used to sort by newest data file, which answers "most recently active". A long
    run still writing, or an old session whose files were touched, took the top row from the
    run somebody had just started. Both are plausible: reading a session rewrites nothing,
    but archiving or merging one does.
    """
    from nttd.monitor.registry import SessionRegistry

    root = tmp_path / "sessions"
    for session_id in ("ses_20260813_090000_aaaaaaaa",
                       "ses_20260813_190000_cccccccc",
                       "ses_20260812_120000_bbbbbbbb"):
        (root / session_id).mkdir(parents=True)

    # The oldest session is the most recently touched, which is what used to decide the order.
    newest_file = root / "ses_20260812_120000_bbbbbbbb" / "snapshots.parquet"
    newest_file.write_bytes(b"")
    os.utime(newest_file, (2_000_000_000, 2_000_000_000))

    assert SessionRegistry(root).session_ids() == [
        "ses_20260813_190000_cccccccc",
        "ses_20260813_090000_aaaaaaaa",
        "ses_20260812_120000_bbbbbbbb",
    ]


def test_a_session_id_without_a_timestamp_still_sorts(tmp_path: Path) -> None:
    """A directory from an older layout must not raise, and must sort last.

    Not by file activity, which was the first attempt: a directory created a moment ago has a
    modification time later than any real session start, so it took the top row.
    """
    from nttd.monitor.registry import SessionRegistry

    root = tmp_path / "sessions"
    (root / "ses_20260813_190000_cccccccc").mkdir(parents=True)
    (root / "legacy-run").mkdir(parents=True)

    order = SessionRegistry(root).session_ids()
    assert order[0] == "ses_20260813_190000_cccccccc"
    assert "legacy-run" in order
