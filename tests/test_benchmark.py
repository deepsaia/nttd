from fastapi.testclient import TestClient

from nttd.api.app import app
from nttd.api.dependencies import snapshot_broker_registry

client = TestClient(app)


# ---------------------------------------------------------------------------
# CompactSnapshot tests
# ---------------------------------------------------------------------------

def test_compact_snapshot_no_company() -> None:
    """Unknown company_id returns company: null."""
    resp = client.get("/state/compact?company_id=999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["company"] is None


def test_compact_snapshot_default_company() -> None:
    """No company_id returns valid compact snapshot."""
    resp = client.get("/state/compact")
    assert resp.status_code == 200
    data = resp.json()
    assert "game_date" in data
    assert "vehicles" in data
    assert "top_towns" in data
    assert "total_stations" in data


# ---------------------------------------------------------------------------
# Heartbeat action scope tests
# ---------------------------------------------------------------------------

def _connect_scoped_agent(agent_id: str, scope: list[int]) -> None:
    client.post("/agents/connect", json={
        "agent_id": agent_id,
        "name": agent_id,
        "company_scope": scope,
    })


def test_heartbeat_action_scope_allowed() -> None:
    """Agent with scope [1] submitting company_id=1 is accepted."""
    _connect_scoped_agent("scope_agent_allow", [1])
    resp = client.post("/session/heartbeat/action", json={
        "agent_id": "scope_agent_allow",
        "action": "ping",
        "params": {"company_id": 1},
    })
    assert resp.status_code == 200
    assert resp.json()["queued"] is True
    client.post("/agents/scope_agent_allow/disconnect")


def test_heartbeat_action_scope_blocked() -> None:
    """Agent with scope [1] submitting company_id=2 is rejected with 403."""
    _connect_scoped_agent("scope_agent_block", [1])
    resp = client.post("/session/heartbeat/action", json={
        "agent_id": "scope_agent_block",
        "action": "ping",
        "params": {"company_id": 2},
    })
    assert resp.status_code == 403
    client.post("/agents/scope_agent_block/disconnect")


def test_heartbeat_action_no_agent_id() -> None:
    """No agent_id — backward compat, action is queued without scope check."""
    resp = client.post("/session/heartbeat/action", json={
        "action": "ping",
        "params": {"company_id": 42},
    })
    assert resp.status_code == 200
    assert resp.json()["queued"] is True


def test_heartbeat_action_unknown_agent() -> None:
    """Unknown agent_id returns 404."""
    resp = client.post("/session/heartbeat/action", json={
        "agent_id": "nonexistent_agent_xyz",
        "action": "ping",
        "params": {},
    })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Snapshot broker lifecycle tests
# ---------------------------------------------------------------------------

def test_snapshot_broker_lifecycle() -> None:
    """Broker is created on connect and deleted on disconnect."""
    agent_id = "broker_test_agent"

    client.post("/agents/connect", json={
        "agent_id": agent_id,
        "name": "Broker Test",
        "company_scope": [0],
    })
    assert agent_id in snapshot_broker_registry

    client.post(f"/agents/{agent_id}/disconnect")
    assert agent_id not in snapshot_broker_registry


# ---------------------------------------------------------------------------
# Benchmark results structure test
# ---------------------------------------------------------------------------

def test_benchmark_results_structure() -> None:
    """GET /benchmark/results returns companies list and date fields."""
    resp = client.get("/benchmark/results")
    assert resp.status_code == 200
    data = resp.json()
    assert "companies" in data
    assert isinstance(data["companies"], list)
    assert "game_days_elapsed" in data
    assert "wall_time_elapsed_s" in data
    assert "start_date" in data
    assert "current_date" in data
