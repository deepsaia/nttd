"""Reading and writing a session's metadata row.

Run with: uv run pytest tests/test_session_writer.py -v
"""
from pathlib import Path

import pytest

from nttd.store.session_writer import (
    read_session,
    update_session,
    write_session,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Return a temporary session directory."""
    d = tmp_path / "test_session"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# session.parquet
# ---------------------------------------------------------------------------


def test_write_and_read_session(session_dir: Path) -> None:
    """Write the metadata row and read it back."""
    write_session(
        session_dir=session_dir,
        session_id="ses_001",
        name="Test Session",
        status="active",
        created_at="2026-04-06T12:00:00Z",
        game_port=4000,
        admin_port=4001,
        pid=12345,
    )

    data = read_session(session_dir)
    assert data is not None
    assert data["session_id"] == "ses_001"
    assert data["name"] == "Test Session"
    assert data["status"] == "active"
    assert data["game_port"] == 4000
    assert data["admin_port"] == 4001
    assert data["pid"] == 12345


def test_write_session_with_settings(session_dir: Path) -> None:
    """Settings block is written and readable."""
    settings = {
        "game_creation.map_x": "8",
        "game_creation.landscape": "0",
    }
    write_session(
        session_dir=session_dir,
        session_id="ses_002",
        settings=settings,
    )

    data = read_session(session_dir)
    assert data is not None
    assert "settings" in data
    assert data["settings"]["game_creation.map_x"] == "8"
    assert data["settings"]["game_creation.landscape"] == "0"


def test_write_session_with_meta(session_dir: Path) -> None:
    """Meta block is written and readable."""
    write_session(
        session_dir=session_dir,
        session_id="ses_003",
        meta={"agent_companies": 4, "runtime_mode": "async_realtime"},
    )

    data = read_session(session_dir)
    assert data is not None
    assert "meta" in data
    assert data["meta"]["agent_companies"] == 4


def test_update_session(session_dir: Path) -> None:
    """Update specific fields in place."""
    write_session(
        session_dir=session_dir,
        session_id="ses_004",
        status="active",
    )

    update_session(session_dir, {
        "session.status": "ended",
        "session.ended_at": "2026-04-06T13:00:00Z",
        "session.end_reason": "manual",
    })

    data = read_session(session_dir)
    assert data is not None
    assert data["status"] == "ended"
    assert data["end_reason"] == "manual"


def test_read_nonexistent_session(tmp_path: Path) -> None:
    """Reading a session that was never written returns None."""
    data = read_session(tmp_path / "nonexistent")
    assert data is None


def test_write_creates_directory(tmp_path: Path) -> None:
    """write_session creates the directory if it doesn't exist."""
    session_dir = tmp_path / "new_session"
    write_session(
        session_dir=session_dir,
        session_id="ses_auto_dir",
    )
    assert (session_dir / "session.parquet").exists()


# agents.conf went with the deleted server-driven gameloop; participant identity
# now comes from the live token registry and spend from POST /report.


