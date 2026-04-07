"""Tests for session-scoped recorder and Parquet fragment writes.

Tests the fragment-based Parquet storage pipeline without a running OpenTTD.

Run with: uv run pytest tests/test_benchmark.py -v
"""
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from nttd.db.recorder import SessionRecorder
from nttd.gameloop.schemas import CycleRecord
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    action_id: str = "test:0:agent1:1:0",
    company_id: int = 0,
    action_type: str = "build_road",
    game_date: int = 18628,
    participant_id: str = "agent1",
) -> ActionEnvelope:
    return ActionEnvelope(
        action_id=action_id,
        company_id=company_id,
        action_type=action_type,
        parameters={"start_tile": 1000, "end_tile": 1010},
        metadata={"game_date": game_date, "participant_id": participant_id,
                  "submitted_at": "2026-04-06T12:00:00Z"},
    )


def _make_result(action_id: str = "test:0:agent1:1:0", status: str = "success") -> ActionResult:
    return ActionResult(action_id=action_id, status=status)


def _make_cycle(connection_id: str = "road-agent", cycle_number: int = 1) -> CycleRecord:
    return CycleRecord(
        connection_id=connection_id,
        session_id="test_session",
        cycle_number=cycle_number,
        game_date=18628,
        observe_ms=50.0,
        decide_ms=1200.0,
        execute_ms=300.0,
        total_ms=1550.0,
        actions_proposed=3,
        actions_executed=3,
        actions_succeeded=2,
        actions_failed=1,
        observation_size_bytes=4096,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def recorder(data_dir: Path) -> SessionRecorder:
    return SessionRecorder("test_session", data_dir=str(data_dir))


# ---------------------------------------------------------------------------
# Recorder lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recorder_start_stop(recorder: SessionRecorder) -> None:
    """Recorder starts and stops cleanly."""
    await recorder.start()
    await recorder.stop()


@pytest.mark.asyncio
async def test_record_action_persists(recorder: SessionRecorder, data_dir: Path) -> None:
    """Actions recorded during a session are flushed to Parquet."""
    await recorder.start()

    envelope = _make_envelope()
    result = _make_result()
    recorder.record_action(envelope, result)

    await recorder._flush_once()
    await recorder.stop()

    actions_path = data_dir / "test_session" / "actions.parquet"
    assert actions_path.exists(), "actions.parquet should exist after flush"

    table = pq.read_table(actions_path)
    assert table.num_rows == 1
    assert table.column("action_id")[0].as_py() == "test:0:agent1:1:0"
    assert table.column("action_type")[0].as_py() == "build_road"
    assert table.column("status")[0].as_py() == "success"


@pytest.mark.asyncio
async def test_record_agent_cycle_persists(recorder: SessionRecorder, data_dir: Path) -> None:
    """Agent cycles are flushed to Parquet."""
    await recorder.start()

    recorder.record_agent_cycle(_make_cycle())

    await recorder._flush_once()
    await recorder.stop()

    cycles_path = data_dir / "test_session" / "agent_cycles.parquet"
    assert cycles_path.exists()

    table = pq.read_table(cycles_path)
    assert table.num_rows == 1
    assert table.column("connection_id")[0].as_py() == "road-agent"
    assert table.column("decide_ms")[0].as_py() == pytest.approx(1200.0, rel=0.01)


@pytest.mark.asyncio
async def test_record_event_persists(recorder: SessionRecorder, data_dir: Path) -> None:
    """Events are flushed to Parquet."""
    await recorder.start()

    recorder.record_event(
        game_date=18628,
        event_type="session_started",
        detail="Session started",
    )

    await recorder._flush_once()
    await recorder.stop()

    events_path = data_dir / "test_session" / "events.parquet"
    assert events_path.exists()

    table = pq.read_table(events_path)
    assert table.num_rows == 1
    assert table.column("event_type")[0].as_py() == "session_started"


@pytest.mark.asyncio
async def test_multiple_flushes_merge(recorder: SessionRecorder, data_dir: Path) -> None:
    """Multiple flushes produce fragments that merge into a single file on stop."""
    await recorder.start()

    # Flush 1
    recorder.record_action(
        _make_envelope(action_id="a:0:agent:1:0"),
        _make_result(action_id="a:0:agent:1:0"),
    )
    await recorder._flush_once()

    # Flush 2
    recorder.record_action(
        _make_envelope(action_id="a:0:agent:2:0", action_type="build_depot"),
        _make_result(action_id="a:0:agent:2:0", status="failed"),
    )
    await recorder._flush_once()

    await recorder.stop()

    actions_path = data_dir / "test_session" / "actions.parquet"
    table = pq.read_table(actions_path)
    assert table.num_rows == 2

    # Fragments should be cleaned up
    fragments_dir = data_dir / "test_session" / "_fragments"
    if fragments_dir.exists():
        remaining = list(fragments_dir.glob("actions_*.parquet"))
        assert len(remaining) == 0, f"Fragments not cleaned up: {remaining}"
