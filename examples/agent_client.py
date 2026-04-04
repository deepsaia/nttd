#!/usr/bin/env python3
"""Example agent client demonstrating the full nttd API flow.

Usage:
    # Start nttd server + create a session first, then:
    uv run python examples/agent_client.py --session-id ses_abc123

    # Or with custom base URL:
    uv run python examples/agent_client.py --base-url http://localhost:8000 --session-id ses_abc123

This script demonstrates:
    1. Connect as an agent
    2. Poll game state (compact snapshot)
    3. Query specific data (GS queries)
    4. Submit actions
    5. Receive snapshots via WebSocket
    6. Disconnect
"""

import argparse
import asyncio
import json

import httpx
import websockets


async def rest_demo(base_url: str, session_id: str) -> None:
    """Run the example agent using REST API."""
    session_url = f"/sessions/{session_id}"

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        # 1. Connect as agent
        print("=== Connect Agent ===")
        resp = await client.post(f"{session_url}/agents/connect", json={
            "agent_id": "example_agent",
            "name": "Example Agent",
            "company_scope": [0],
        })
        print(json.dumps(resp.json(), indent=2))

        # 2. Get compact state snapshot
        print("\n=== Compact State ===")
        resp = await client.get(f"{session_url}/state/compact", params={"company_id": 0})
        state = resp.json()
        print(f"  Date: {state.get('game_date', '?')}")
        print(f"  Balance: {state.get('company', {}).get('balance', '?')}")
        print(f"  Vehicles: {state.get('vehicles', {}).get('total', 0)}")

        # 3. GS queries for specific data
        print("\n=== Towns ===")
        resp = await client.post(f"{session_url}/state/gs/query", params={"action": "get_towns"}, json={})
        towns = resp.json().get("result", [])
        for town in towns[:5]:
            print(f"  {town['name']}: pop {town['population']} at ({town.get('x')}, {town.get('y')})")

        print("\n=== Engines (road vehicles) ===")
        resp = await client.post(
            f"{session_url}/state/gs/query",
            params={"action": "get_engines"},
            json={"company_id": 0, "vehicle_type": 1},
        )
        engines = resp.json().get("result", [])
        for eng in engines[:5]:
            print(f"  [{eng['id']}] {eng.get('name', '?')} — cargo: {eng.get('cargo_label', '?')}")

        # 4. Find buildable spots
        if towns:
            print("\n=== Bus Stop Spots ===")
            resp = await client.post(
                f"{session_url}/state/gs/query",
                params={"action": "find_bus_stop_spots"},
                json={"town_id": towns[0]["id"], "company_id": 0, "max_results": 3},
            )
            spots = resp.json().get("result", [])
            for spot in spots:
                print(f"  tile={spot['tile']} at ({spot.get('x')}, {spot.get('y')})")

        # 5. Submit an action (example: build a bus stop)
        print("\n=== Submit Action (example) ===")
        resp = await client.post(f"{session_url}/actions/submit", json={
            "action_id": "demo_001",
            "company_id": 0,
            "action_type": "build_road_stop",
            "parameters": {"tile": 12345, "length": 1, "is_truck": False},
            "mode": "atomic",
        })
        result = resp.json()
        print(f"  Status: {result.get('status')} — {result.get('error', 'ok')}")

        # 6. Check action status
        print("\n=== Action Status ===")
        resp = await client.get(f"{session_url}/actions/demo_001/status")
        print(f"  {resp.json().get('status')}")

        # 7. Disconnect
        print("\n=== Disconnect ===")
        resp = await client.post(f"{session_url}/agents/example_agent/disconnect")
        print(json.dumps(resp.json(), indent=2))

    print("\nDone. Agent lifecycle complete.")


async def ws_demo(base_url: str, session_id: str) -> None:
    """Run the example agent using WebSocket for real-time snapshots."""
    session_url = f"/sessions/{session_id}"
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    agent_id = "example_ws_agent"

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        print("=== Connect Agent ===")
        resp = await client.post(f"{session_url}/agents/connect", json={
            "agent_id": agent_id,
            "name": "Example WS Agent",
            "company_scope": [0],
        })
        print(json.dumps(resp.json(), indent=2))

    # Open WebSocket and receive snapshots
    ws_uri = f"{ws_url}/ws/{session_id}/{agent_id}"
    print(f"\n=== WebSocket: {ws_uri} ===")
    print("Listening for snapshots (Ctrl+C to stop)...\n")

    try:
        async with websockets.connect(ws_uri) as ws:
            for i in range(5):
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

    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        await client.post(f"{session_url}/agents/{agent_id}/disconnect")
    print("\nDisconnected. Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="nttd API client example")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True, help="Session ID (e.g. ses_abc123)")
    parser.add_argument("--ws", action="store_true", help="Use WebSocket mode")
    args = parser.parse_args()

    if args.ws:
        asyncio.run(ws_demo(args.base_url, args.session_id))
    else:
        asyncio.run(rest_demo(args.base_url, args.session_id))
