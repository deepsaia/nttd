"""Deleting a session from the monitor removes its files, and refuses when it should not.

The delete button is the only control on the page that changes anything, and it is not
undoable, so the guards are the interesting part:

  * POST only. A GET link would be followed by prefetchers and crawlers, and a refresh would
    re-fire it. There is no GET route that deletes.
  * A running session is refused. Removing the directory under a live recorder leaves the
    server flushing into a path that no longer exists.
  * The id goes through the same allowlist as every other path build, so a crafted id cannot
    reach outside the sessions root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nttd.monitor.registry import SessionRegistry
from nttd.store import session_paths
from nttd.store.session_remover import remove_session


class _ExplodingRegistry:
    """Fails loudly if consulted. Used to prove a bad id never reaches it."""

    root = Path("/nonexistent")

    def is_live(self, session_id: str) -> bool:
        raise AssertionError(f"the registry was asked about {session_id!r}")


class _ExplodingRegistryServer:
    registry = _ExplodingRegistry()


def _make_session(root: Path, session_id: str) -> Path:
    directory = root / session_id
    directory.mkdir(parents=True)
    (directory / "snapshots.parquet").write_bytes(b"not really parquet")
    (directory / "final.sav").write_bytes(b"not really a save")
    (directory / "_fragments").mkdir()
    (directory / "_fragments" / "snapshots_0.parquet").write_bytes(b"fragment")
    return directory


def test_it_removes_the_whole_directory(tmp_path: Path) -> None:
    directory = _make_session(tmp_path, "ses_20260814_120000_abcd1234")
    assert remove_session("ses_20260814_120000_abcd1234", tmp_path) is True
    assert not directory.exists()


def test_deleting_a_session_that_is_already_gone_is_not_an_error(tmp_path: Path) -> None:
    """Two clicks on the same button, or a directory cleaned up by hand."""
    assert remove_session("ses_20260814_120000_abcd1234", tmp_path) is False


def test_a_crafted_id_cannot_escape_the_sessions_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "must_survive"
    outside.mkdir(exist_ok=True)
    for attempt in ("..", "../must_survive", "ses/../..", "/etc"):
        with pytest.raises(session_paths.InvalidSessionIdError):
            remove_session(attempt, tmp_path)
    assert outside.exists()


def test_it_deletes_from_the_root_it_was_given(tmp_path: Path) -> None:
    """The monitor can be pointed at another directory; deleting from the default would
    remove a different session that happens to share the id."""
    shown = tmp_path / "shown"
    other = tmp_path / "other"
    kept = _make_session(other, "ses_20260814_120000_abcd1234")
    _make_session(shown, "ses_20260814_120000_abcd1234")

    remove_session("ses_20260814_120000_abcd1234", shown)
    assert kept.exists(), "the session in the other root must be untouched"


def test_a_running_session_is_reported_live_and_so_refused(tmp_path: Path) -> None:
    """is_live is what the handler checks before deleting. Unreadable counts as live."""
    registry = SessionRegistry(sessions_dir=tmp_path)
    _make_session(tmp_path, "ses_20260814_120000_abcd1234")
    # No session.json at all, so the feed cannot be read: it must not be deletable.
    assert registry.is_live("ses_20260814_120000_abcd1234") is True


def test_a_bad_id_is_rejected_before_anything_else_is_asked_about_it() -> None:
    """Found by driving the real server, not by the unit tests: the handler checked liveness
    first, is_live could not read "../escape" so it answered "live", and the reply was a 500
    "still running" rather than a 400 "not a session id".

    Asserted as behaviour: the registry must not be consulted at all for an id that is not one.
    """
    from nttd.monitor.request_handler import MonitorHandler

    handler = MonitorHandler.__new__(MonitorHandler)
    handler.server = _ExplodingRegistryServer()

    for attempt in ("", "../escape", "..", "has spaces", "a" * 200):
        with pytest.raises(session_paths.InvalidSessionIdError):
            handler._delete(attempt)


def test_there_is_no_get_route_that_deletes() -> None:
    """A delete reachable by GET would fire on prefetch."""
    import inspect

    from nttd.monitor import request_handler

    source = inspect.getsource(request_handler.MonitorHandler.do_GET)
    assert "remove_session" not in source
    assert request_handler.DELETE_PATH not in source


def test_the_sidebar_offers_a_delete_button_per_finished_session() -> None:
    from nttd.monitor import page

    finished = {
        "session_id": "ses_20260814_120000_abcd1234", "name": "jolly-nova-20260814-1139ist",
        "live": False, "steps": 366, "rating": 25,
    }
    row = page._delete_control(finished)
    assert 'method="post"' in row
    assert 'action="/delete"' in row
    assert finished["session_id"] in row


def test_a_live_session_shows_a_disabled_control_with_the_reason() -> None:
    from nttd.monitor import page

    row = page._delete_control({"session_id": "ses_x", "name": "n", "live": True})
    assert "<form" not in row, "a running session must not be submittable"
    assert "still running" in row
