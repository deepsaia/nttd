"""Tests for HOCON conf_writer: session.conf and agents.conf read/write.

Run with: uv run pytest tests/test_conf_writer.py -v
"""
from pathlib import Path

import pytest

from nttd.db.conf_writer import (
    read_session_conf,
    update_session_conf,
    write_session_conf,
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
# session.conf tests
# ---------------------------------------------------------------------------


def test_write_and_read_session_conf(session_dir: Path) -> None:
    """Write session.conf and read it back."""
    write_session_conf(
        session_dir=session_dir,
        session_id="ses_001",
        name="Test Session",
        status="active",
        created_at="2026-04-06T12:00:00Z",
        game_port=4000,
        admin_port=4001,
        pid=12345,
    )

    data = read_session_conf(session_dir)
    assert data is not None
    assert data["session_id"] == "ses_001"
    assert data["name"] == "Test Session"
    assert data["status"] == "active"
    assert data["game_port"] == 4000
    assert data["admin_port"] == 4001
    assert data["pid"] == 12345


def test_write_session_conf_with_settings(session_dir: Path) -> None:
    """Settings block is written and readable."""
    settings = {
        "game_creation.map_x": "8",
        "game_creation.landscape": "0",
    }
    write_session_conf(
        session_dir=session_dir,
        session_id="ses_002",
        settings=settings,
    )

    data = read_session_conf(session_dir)
    assert data is not None
    assert "settings" in data
    assert data["settings"]["game_creation.map_x"] == "8"
    assert data["settings"]["game_creation.landscape"] == "0"


def test_write_session_conf_with_meta(session_dir: Path) -> None:
    """Meta block is written and readable."""
    write_session_conf(
        session_dir=session_dir,
        session_id="ses_003",
        meta={"agent_companies": 4, "runtime_mode": "async_realtime"},
    )

    data = read_session_conf(session_dir)
    assert data is not None
    assert "meta" in data
    assert data["meta"]["agent_companies"] == 4


def test_update_session_conf(session_dir: Path) -> None:
    """Update specific fields in session.conf."""
    write_session_conf(
        session_dir=session_dir,
        session_id="ses_004",
        status="active",
    )

    update_session_conf(session_dir, {
        "session.status": "ended",
        "session.ended_at": "2026-04-06T13:00:00Z",
        "session.end_reason": "manual",
    })

    data = read_session_conf(session_dir)
    assert data is not None
    assert data["status"] == "ended"
    assert data["end_reason"] == "manual"


def test_read_nonexistent_session_conf(tmp_path: Path) -> None:
    """Reading a non-existent session.conf returns None."""
    data = read_session_conf(tmp_path / "nonexistent")
    assert data is None


def test_write_creates_directory(tmp_path: Path) -> None:
    """write_session_conf creates the directory if it doesn't exist."""
    session_dir = tmp_path / "new_session"
    write_session_conf(
        session_dir=session_dir,
        session_id="ses_auto_dir",
    )
    assert (session_dir / "session.parquet").exists()


# ---------------------------------------------------------------------------
# agents.conf tests
# ---------------------------------------------------------------------------


