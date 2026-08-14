"""The page is pushed to, and a source edit restarts the server that renders it.

The page used to carry a meta refresh. Polling is wrong in both directions at once: it redraws
when nothing happened, and it waits up to a whole interval when something did. A step takes
about a minute, so most reloads showed an identical page.

Two fingerprints, watched separately because they want different responses:

  DATA  a session wrote. The browser reloads.
  CODE  a monitor module was edited. The HTML is rendered FROM those modules, so reloading the
        browser against a server still running the old import shows the old page, which reads
        as the edit not working. The server re-executes instead.

Verified live before these were written: touching a monitor source file produced an `event: code`
on the stream, a second "Monitor serving" line in the log, and a page that still answered 200.
Note that os.execv keeps the same pid, so a pid comparison is NOT a test of this.
"""

from __future__ import annotations

import time
from pathlib import Path

from nttd.monitor.watcher import Watcher


def test_a_new_session_directory_changes_the_data_revision(tmp_path: Path) -> None:
    watcher = Watcher(tmp_path)
    before = watcher.data_revision()
    (tmp_path / "ses_20260814_120000_abcd1234").mkdir()
    assert watcher.data_revision() != before


def test_a_written_fragment_changes_the_data_revision(tmp_path: Path) -> None:
    """The case that matters most: a recorder adding one file mid-run."""
    session = tmp_path / "ses_20260814_120000_abcd1234"
    fragments = session / "_fragments"
    fragments.mkdir(parents=True)
    watcher = Watcher(tmp_path)
    before = watcher.data_revision()
    time.sleep(0.01)
    (fragments / "snapshots_0001.parquet").write_bytes(b"x")
    assert watcher.data_revision() != before


def test_deleting_a_session_changes_the_data_revision(tmp_path: Path) -> None:
    """So the list refreshes itself after the delete button is used."""
    session = tmp_path / "ses_20260814_120000_abcd1234"
    session.mkdir()
    watcher = Watcher(tmp_path)
    before = watcher.data_revision()
    session.rmdir()
    assert watcher.data_revision() != before


def test_a_missing_sessions_directory_is_not_an_error(tmp_path: Path) -> None:
    """The monitor can be started before anything has run."""
    watcher = Watcher(tmp_path / "not-there")
    assert watcher.data_revision() == "none"


def test_editing_a_monitor_module_changes_the_code_revision(tmp_path: Path) -> None:
    watcher = Watcher(tmp_path)
    before = watcher.code_revision()
    assert "page.py" in before, "the rendering modules are what is watched"
    time.sleep(0.01)
    Path(__import__("nttd.monitor.page", fromlist=["x"]).__file__).touch()
    assert watcher.code_revision() != before


def test_the_two_revisions_are_independent(tmp_path: Path) -> None:
    """A session write must not look like a code edit: one reloads, the other re-execs."""
    watcher = Watcher(tmp_path)
    code = watcher.code_revision()
    (tmp_path / "ses_20260814_120000_abcd1234").mkdir()
    assert watcher.code_revision() == code


def test_the_stream_route_exists_and_is_not_the_delete_route() -> None:
    from nttd.monitor import request_handler

    assert request_handler.LIVE_PATH == "/live"
    assert request_handler.LIVE_PATH != request_handler.DELETE_PATH
    # A stream that never says anything looks identical to a hung server, so it beats.
    assert request_handler.KEEPALIVE_SECONDS > request_handler.WATCH_INTERVAL_SECONDS
