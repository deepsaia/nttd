import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nttd.api.app import app

client = TestClient(app)


def test_websocket_rejects_unknown_agent() -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/nonexistent_agent"):
            pass


def test_websocket_snapshot_delivery() -> None:
    # First connect an agent
    client.post("/agents/connect", json={
        "agent_id": "ws_test_agent",
        "name": "WS Test",
        "company_scope": [1],
    })
    client.post("/agents/ws_test_agent/subscriptions", json={
        "channel": "companies",
        "subscription_type": "entity",
        "cadence": 1,
    })

    with client.websocket_connect("/ws/ws_test_agent") as ws:
        # Send ping, expect pong
        ws.send_json({"type": "ping"})
        resp = ws.receive_json()
        assert resp["type"] == "pong"

    # Cleanup
    client.post("/agents/ws_test_agent/disconnect")


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_session_status() -> None:
    resp = client.get("/session/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "game_date" in data
    assert "mode" in data


def test_pause_unpause() -> None:
    resp = client.post("/session/pause")
    assert resp.json()["paused"] is True

    resp = client.post("/session/unpause")
    assert resp.json()["paused"] is False


def test_set_speed() -> None:
    resp = client.post("/session/speed?speed=2")
    assert resp.json()["speed"] == 2


def test_set_mode() -> None:
    resp = client.post("/session/mode?mode=async_realtime")
    assert resp.json()["mode"] == "async_realtime"


def test_agent_lifecycle() -> None:
    # connect
    resp = client.post("/agents/connect", json={
        "agent_id": "test_agent_1",
        "name": "Test Agent",
        "company_scope": [1],
    })
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "test_agent_1"

    # status
    resp = client.get("/agents/test_agent_1/status")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True

    # list
    resp = client.get("/agents/list")
    assert len(resp.json()) >= 1

    # subscribe
    resp = client.post("/agents/test_agent_1/subscriptions", json={
        "channel": "companies",
        "subscription_type": "entity",
        "cadence": 1,
    })
    assert resp.json()["subscribed"] is True

    # list subscriptions
    resp = client.get("/agents/test_agent_1/subscriptions")
    assert len(resp.json()) == 1

    # unsubscribe
    resp = client.delete("/agents/test_agent_1/subscriptions/companies")
    assert resp.json()["removed"] is True

    # disconnect
    resp = client.post("/agents/test_agent_1/disconnect")
    assert resp.json()["disconnected"] is True

    # gone
    resp = client.get("/agents/test_agent_1/status")
    assert resp.status_code == 404


def test_full_state() -> None:
    resp = client.get("/state/full")
    assert resp.status_code == 200
    data = resp.json()
    assert "game" in data
    assert "companies" in data
    assert "towns" in data


def test_submit_action() -> None:
    resp = client.post("/actions/submit", json={
        "action_id": "act_001",
        "company_id": 1,
        "action_type": "buy_vehicle",
        "parameters": {"vehicle_type": "train"},
    })
    assert resp.status_code == 200
    assert resp.json()["action_id"] == "act_001"
    assert resp.json()["status"] == "pending"

    # check status
    resp = client.get("/actions/act_001/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    # recent
    resp = client.get("/actions/recent")
    assert len(resp.json()) >= 1
