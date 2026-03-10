#!/usr/bin/env python3
"""Example agent client demonstrating the full nttd API flow.

Usage:
    # Start OpenTTD + nttd first, then:
    uv run python examples/agent_client.py

    # Or with custom base URL:
    NTTD_URL=http://localhost:8000 uv run python examples/agent_client.py

This script demonstrates:
    1. Connect as an agent
    2. Subscribe to observations
    3. Poll game state (REST)
    4. Receive snapshots via WebSocket
    5. Submit actions
    6. Disconnect
"""

import asyncio
import json
import os
import sys

import httpx
import websockets

BASE_URL = os.environ.get("NTTD_URL", "http://127.0.0.1:8000")
WS_URL = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
AGENT_ID = "example_agent_1"


def main() -> None:
    """Run the example agent using REST API."""
    client = httpx.Client(base_url=BASE_URL, timeout=10)

    # 1. Check health
    print("=== Health Check ===")
    resp = client.get("/health")
    print(json.dumps(resp.json(), indent=2))
    if resp.json().get("openttd") != "connected":
        print("Warning: OpenTTD not connected. Running in offline mode.")

    # 2. Connect as agent
    print("\n=== Connect Agent ===")
    resp = client.post("/agents/connect", json={
        "agent_id": AGENT_ID,
        "name": "Example Agent",
        "company_scope": [1],
    })
    print(json.dumps(resp.json(), indent=2))

    # 3. Subscribe to companies and towns
    print("\n=== Subscribe ===")
    for channel in ["companies", "towns"]:
        resp = client.post(f"/agents/{AGENT_ID}/subscriptions", json={
            "channel": channel,
            "subscription_type": "entity",
            "cadence": 1,
        })
        print(f"  {channel}: {resp.json()}")

    # 4. Get session status
    print("\n=== Session Status ===")
    resp = client.get("/session/status")
    status = resp.json()
    print(json.dumps(status, indent=2))

    # 5. Get full state snapshot
    print("\n=== Full State Snapshot ===")
    resp = client.get("/state/full")
    state = resp.json()
    print(f"  Game date: {state['game']['game_date']}")
    print(f"  Map: {state['game']['map_width']}x{state['game']['map_height']}")
    print(f"  Companies: {len(state['companies'])}")
    print(f"  Towns: {len(state['towns'])}")

    # 6. Submit an action
    print("\n=== Submit Action ===")
    resp = client.post("/actions/submit", json={
        "action_id": "example_act_001",
        "company_id": 1,
        "action_type": "buy_vehicle",
        "parameters": {"vehicle_type": "bus"},
    })
    print(json.dumps(resp.json(), indent=2))

    # 7. Check action status
    print("\n=== Action Status ===")
    resp = client.get("/actions/example_act_001/status")
    print(json.dumps(resp.json(), indent=2))

    # 8. Disconnect
    print("\n=== Disconnect ===")
    resp = client.post(f"/agents/{AGENT_ID}/disconnect")
    print(json.dumps(resp.json(), indent=2))

    print("\nDone. Agent lifecycle complete.")
    client.close()


async def ws_main() -> None:
    """Run the example agent using WebSocket for real-time snapshots."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        # Connect agent via REST first
        print("=== Connect Agent ===")
        resp = await client.post("/agents/connect", json={
            "agent_id": AGENT_ID,
            "name": "Example WS Agent",
            "company_scope": [1],
        })
        print(json.dumps(resp.json(), indent=2))

        # Subscribe
        await client.post(f"/agents/{AGENT_ID}/subscriptions", json={
            "channel": "companies",
            "subscription_type": "entity",
            "cadence": 1,
        })
        print("Subscribed to companies")

    # Open WebSocket and receive snapshots
    ws_uri = f"{WS_URL}/ws/{AGENT_ID}"
    print(f"\n=== WebSocket: {ws_uri} ===")
    print("Listening for snapshots (Ctrl+C to stop)...\n")

    try:
        async with websockets.connect(ws_uri) as ws:
            for i in range(5):  # receive 5 snapshots then stop
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                msg = json.loads(raw)
                if msg["type"] == "snapshot":
                    game = msg["data"]["game"]
                    print(f"  [{i+1}] date={game['game_date']} "
                          f"paused={game['paused']} "
                          f"companies={len(msg['data']['companies'])}")
    except asyncio.TimeoutError:
        print("Timed out waiting for snapshots.")
    except KeyboardInterrupt:
        print("Stopped.")

    # Disconnect
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        await client.post(f"/agents/{AGENT_ID}/disconnect")
    print("\nDisconnected. Done.")


if __name__ == "__main__":
    if "--ws" in sys.argv:
        asyncio.run(ws_main())
    else:
        main()
