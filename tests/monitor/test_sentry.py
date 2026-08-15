"""The sentry, which is the only part of the monitor that can end a run.

Tested more tightly than the rest for that reason. The default must be to do nothing, and
when armed it must act on exactly one class of session: live, and tripping a bad rule.
Anything looser ends a run somebody is waiting on.
"""

from __future__ import annotations

from typing import Any

import pytest

from nttd.monitor.sentry import Sentry


class _FakeRegistry:
    """Stands in for SessionRegistry with a fixed set of verdicts."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    def entries(self, limit: int = 40) -> list[dict[str, Any]]:
        return self._entries


class _Recorder:
    """Records the stop requests instead of making them."""

    def __init__(self, fail: bool = False) -> None:
        self.urls: list[str] = []
        self._fail = fail

    def post(self, url: str, timeout: int = 0) -> Any:
        self.urls.append(url)
        if self._fail:
            raise OSError("connection refused")
        return self

    def raise_for_status(self) -> None:
        return None


def _entry(session_id: str, live: bool, level: str | None) -> dict[str, Any]:
    verdicts = []
    if level:
        verdicts = [{
            "level": level, "rule": "no vehicles",
            "detail": "22 stations, no vehicles",
            "why_it_matters": "stations do not earn",
        }]
    return {
        "meta": {"session_id": session_id, "live": live},
        "health": {"level": level or "ok", "summary": "x"},
        "verdicts": verdicts,
    }


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    import requests

    rec = _Recorder()
    monkeypatch.setattr(requests, "post", rec.post)
    return rec


# ----------------------------------------------------------------------


def test_unarmed_it_never_stops_anything(recorder: _Recorder) -> None:
    """The default. A false positive on a two hour tier is expensive."""
    registry = _FakeRegistry([_entry("ses_a", live=True, level="bad")])
    sentry = Sentry(registry, base_url="http://127.0.0.1:8000", armed=False)
    assert sentry.sweep() == []
    assert recorder.urls == []


def test_armed_it_stops_a_live_session_that_tripped_a_bad_rule(recorder: _Recorder) -> None:
    registry = _FakeRegistry([_entry("ses_a", live=True, level="bad")])
    sentry = Sentry(registry, base_url="http://127.0.0.1:8000", armed=True)
    acted = sentry.sweep()
    assert [a["session_id"] for a in acted] == ["ses_a"]
    assert recorder.urls == [
        "http://127.0.0.1:8000/v1/operator/admin/sessions/ses_a/stop",
    ]


def test_a_warning_is_not_enough_to_end_a_run(recorder: _Recorder) -> None:
    registry = _FakeRegistry([_entry("ses_a", live=True, level="warn")])
    sentry = Sentry(registry, base_url="http://x", armed=True)
    assert sentry.sweep() == []
    assert recorder.urls == []


def test_an_ended_session_is_left_alone(recorder: _Recorder) -> None:
    """Its rules trip by definition once it has stopped, and stopping it again is noise."""
    registry = _FakeRegistry([_entry("ses_a", live=False, level="bad")])
    sentry = Sentry(registry, base_url="http://x", armed=True)
    assert sentry.sweep() == []
    assert recorder.urls == []


def test_it_stops_a_session_once_and_not_on_every_sweep(recorder: _Recorder) -> None:
    """The sweep runs every minute and the session takes a moment to actually end."""
    registry = _FakeRegistry([_entry("ses_a", live=True, level="bad")])
    sentry = Sentry(registry, base_url="http://x", armed=True)
    assert len(sentry.sweep()) == 1
    assert sentry.sweep() == []
    assert len(recorder.urls) == 1


def test_a_healthy_session_is_untouched(recorder: _Recorder) -> None:
    registry = _FakeRegistry([_entry("ses_a", live=True, level=None)])
    sentry = Sentry(registry, base_url="http://x", armed=True)
    assert sentry.sweep() == []
    assert recorder.urls == []


def test_a_failed_stop_is_retried_on_the_next_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marking it stopped when the request failed would leave the run going, unwatched."""
    import requests

    rec = _Recorder(fail=True)
    monkeypatch.setattr(requests, "post", rec.post)
    registry = _FakeRegistry([_entry("ses_a", live=True, level="bad")])
    sentry = Sentry(registry, base_url="http://x", armed=True)
    assert sentry.sweep() == []
    assert sentry.sweep() == []
    assert len(rec.urls) == 2


def test_the_base_url_is_used_without_a_doubled_slash(recorder: _Recorder) -> None:
    registry = _FakeRegistry([_entry("ses_a", live=True, level="bad")])
    Sentry(registry, base_url="http://host:8000/", armed=True).sweep()
    assert recorder.urls == ["http://host:8000/v1/operator/admin/sessions/ses_a/stop"]
