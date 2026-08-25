"""The result is scored only after the recorded traces exist on disk.

The scored figures in result.parquet come from the recorded artifacts, which are read
the per-snapshot series out of ``snapshots.parquet``. That file does not exist during a run:
the recorder writes fragments as it goes and only merges them into ``snapshots.parquet`` when
it stops.

``stop_session`` used to score first and shut the runtime down second, and the recorder is
stopped by the shutdown. So the metrics read a file that was not there yet, ``_read_series``
returned None, and compute() returned a zeroed record. Measured on a real completed session,
ses_20260813_214540_7e125597: the written result held vehicles_final 0, stations_final 0,
value_at_50pct 0, cargo_per_vehicle 0.0, while recomputing the same session from disk
afterwards gave 30, 6, 37909 and 117.53. Silent, and it applied to every run ever recorded.

These tests pin the order rather than the values, because the order is the thing that broke.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nttd.runtime.session_manager import SessionManager
from nttd.store.recorder import SessionRecorder


class _CallOrder:
    """Records the sequence of lifecycle calls a stop makes."""

    def __init__(self) -> None:
        self.calls: list[str] = []


class _StubRecorder:
    def __init__(self, order: _CallOrder) -> None:
        self._order = order

    async def stop(self) -> None:
        self._order.calls.append("traces_finalized")


class _StubRuntime:
    def __init__(self, order: _CallOrder) -> None:
        self.recorder = _StubRecorder(order)
        self.game_port = 3979
        self.admin_port = 3977
        self._order = order

    async def shutdown(self) -> None:
        self._order.calls.append("shutdown")


@pytest.fixture
def stopped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _CallOrder:
    """Drive stop_session with everything external stubbed out."""
    order = _CallOrder()
    manager = SessionManager.__new__(SessionManager)
    manager.runtimes = {"ses_test": _StubRuntime(order)}
    manager.sessions_dir = tmp_path

    async def _capture(session_id: str, runtime: Any) -> None:
        order.calls.append("save_captured")
        return None

    def _write(session_id: str, runtime: Any, end_reason: str, final_save: Any) -> None:
        order.calls.append("result_written")

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(manager, "_capture_final_save", _capture)
    monkeypatch.setattr(manager, "_write_result", _write)
    monkeypatch.setattr(manager, "_release_ports", lambda *a: None)
    monkeypatch.setattr("nttd.runtime.session_manager.session_repo.end_session", _noop)
    monkeypatch.setattr("nttd.runtime.session_manager.session_repo.update_session_pid", _noop)

    import asyncio

    asyncio.run(manager.stop_session("ses_test"))
    return order


def test_traces_are_finalized_before_the_result_is_scored(stopped: _CallOrder) -> None:
    """The bug, stated as an order: snapshots.parquet must exist before metrics read it."""
    calls = stopped.calls
    assert "traces_finalized" in calls, "the recorder is never finalized before scoring"
    assert calls.index("traces_finalized") < calls.index("result_written")


def test_the_save_is_still_captured_before_anything_is_torn_down(stopped: _CallOrder) -> None:
    """Capturing the save needs the live admin connection, so it stays first."""
    calls = stopped.calls
    assert calls.index("save_captured") < calls.index("traces_finalized")


def test_the_runtime_is_shut_down_last(stopped: _CallOrder) -> None:
    """Scoring reads the in-memory world, so shutdown must not precede it."""
    calls = stopped.calls
    assert calls.index("result_written") < calls.index("shutdown")


@pytest.mark.asyncio
async def test_stopping_the_recorder_twice_is_harmless(tmp_path: Path) -> None:
    """stop_session finalizes the traces, and SessionRuntime.shutdown stops it again."""
    recorder = SessionRecorder("ses_twice", data_dir=str(tmp_path))
    await recorder.start()
    recorder.record_event(game_date=18628, event_type="session_started", detail="x")
    await recorder.stop()
    await recorder.stop()

    events = tmp_path / "ses_twice" / "events.parquet"
    assert events.exists(), "the first stop must still have merged the fragments"
