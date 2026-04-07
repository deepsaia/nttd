"""API integration tests for health, admin, and session-scoped routes.

Tests the HTTP API layer using FastAPI TestClient with lifespan events.
Routes are session-scoped (e.g., /admin/sessions/{session_id}).

Run with: uv run pytest tests/test_api.py -v
"""
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Use a temp dir for sessions to avoid polluting the project
_TEST_SESSIONS_DIR = "/tmp/nttd_test_sessions_api"
os.environ["NTTD_SESSIONS_DIR"] = _TEST_SESSIONS_DIR

from nttd.api.app import app  # noqa: E402 -- env must be set before import


@pytest.fixture(autouse=True)
def _clean_test_sessions() -> Any:
    """Clean up test sessions before each test."""
    d = Path(_TEST_SESSIONS_DIR)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    yield
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    """TestClient with lifespan so session_manager is initialized."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_session(client: TestClient, name: str = "test") -> str:
    resp = client.post("/admin/sessions/new", json={"name": name})
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "active_sessions" in data


# ---------------------------------------------------------------------------
# Admin session CRUD
# ---------------------------------------------------------------------------


def test_create_session(client: TestClient) -> None:
    resp = client.post("/admin/sessions/new", json={"name": "TestSession"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["status"] == "pending"


def test_list_sessions(client: TestClient) -> None:
    _create_session(client, "list_test")
    resp = client.get("/admin/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)
    assert len(data["sessions"]) >= 1


def test_get_session_by_id(client: TestClient) -> None:
    sid = _create_session(client, "get_test")
    resp = client.get(f"/admin/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == sid


def test_get_session_404(client: TestClient) -> None:
    resp = client.get("/admin/sessions/nonexistent_session_xyz")
    assert resp.status_code == 404


def test_session_settings(client: TestClient) -> None:
    sid = _create_session(client, "settings_test")
    resp = client.post(f"/admin/sessions/{sid}/settings", json={
        "settings": {"game_creation.map_x": "8", "game_creation.map_y": "8"},
    })
    assert resp.status_code == 200

    resp = client.get(f"/admin/sessions/{sid}")
    assert resp.status_code == 200
    settings = resp.json().get("settings", {})
    assert settings.get("game_creation.map_x") == "8"


def test_delete_session(client: TestClient) -> None:
    sid = _create_session(client, "delete_test")
    resp = client.delete(f"/admin/sessions/{sid}")
    assert resp.status_code == 200

    resp = client.get(f"/admin/sessions/{sid}")
    assert resp.status_code == 404
