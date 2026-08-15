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


def test_a_reload_yields_to_a_click_instead_of_racing_it() -> None:
    """Live updates must not make the page unusable.

    A running session writes many times a second and each write reloaded the page, so a click
    on a session in the sidebar was cancelled by a reload before it could navigate: the view
    could not be opened at all. Writes are coalesced, and an interaction holds the reload off
    long enough for the click to win.
    """
    from nttd.monitor.assets import LIVE_BODY_JS

    assert "mousedown" in LIVE_BODY_JS, "an interaction has to hold the reload off"
    assert "clearTimeout" in LIVE_BODY_JS, "writes are coalesced, not reloaded one by one"
    assert "es.close()" in LIVE_BODY_JS, "leaving closes the stream rather than resetting it"


def test_a_reader_closing_the_page_is_not_logged_as_a_server_error() -> None:
    """Every navigation drops the /live socket, and the base class prints a traceback per drop.

    Measured: a session view left open filled the console with ConnectionResetError stacks,
    which is noise that hides anything real.
    """
    import sys
    from unittest.mock import patch

    from nttd.monitor.server import MonitorServer

    with patch.object(sys, "exc_info", return_value=(ConnectionResetError, ConnectionResetError(54), None)), \
         patch("http.server.ThreadingHTTPServer.handle_error") as base:
        MonitorServer.handle_error(None, object(), ("127.0.0.1", 5000))  # type: ignore[arg-type]
    base.assert_not_called()
