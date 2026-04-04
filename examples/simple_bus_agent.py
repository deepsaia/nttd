#!/usr/bin/env python3
"""Minimal standalone agent — builds a bus route between two towns.

Demonstrates the full observe → decide → interpret → execute cycle.
The agent decides on actions and outputs them as a structured list.
The interpreter validates and submits them to the nttd REST API.

Usage:
    uv run python examples/simple_bus_agent.py --session-id ses_abc123
    uv run python examples/simple_bus_agent.py --session-id ses_abc123 --company-id 0
"""

import argparse
import asyncio
import logging

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bus_agent")


# ── Observation helpers ────────────────────────────────────────────────

async def observe_compact(client: httpx.AsyncClient, session_url: str, company_id: int) -> dict:
    """Get compact game state snapshot."""
    resp = await client.get(f"{session_url}/state/compact", params={"company_id": company_id})
    resp.raise_for_status()
    return resp.json()


async def gs_query(client: httpx.AsyncClient, session_url: str, action: str, params: dict | None = None) -> list | dict:
    """Run a GS query and return the result."""
    resp = await client.post(f"{session_url}/state/gs/query", params={"action": action}, json=params or {})
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", data)


# ── Interpreter — sends action list to nttd for execution ─────────────

async def interpret_actions(
    client: httpx.AsyncClient, session_url: str, actions: list[dict], company_id: int,
) -> list[dict]:
    """Submit an agent's action list to the interpreter endpoint for execution."""
    if not actions:
        return []
    resp = await client.post(
        f"{session_url}/actions/interpret",
        json=actions,
        params={"company_id": company_id},
    )
    resp.raise_for_status()
    results = resp.json()
    for i, result in enumerate(results):
        status = result.get("status", "unknown")
        if status != "success":
            log.warning("  action %d (%s) -> %s: %s", i, actions[i]["action_type"], status, result.get("error", ""))
        else:
            log.info("  action %d (%s) -> success", i, actions[i]["action_type"])
    return results


# ── Decision logic ─────────────────────────────────────────────────────

def decide_scout(towns: list[dict]) -> tuple[dict, dict]:
    """Pick the two largest towns for the bus route."""
    towns.sort(key=lambda t: t.get("population", 0), reverse=True)
    town_a = towns[0]
    town_b = towns[min(1, len(towns) - 1)]
    log.info("Towns: %s (pop %d), %s (pop %d)",
             town_a["name"], town_a["population"],
             town_b["name"], town_b["population"])
    return town_a, town_b


def decide_build(stop_a: int, stop_b: int, depot_tile: int) -> list[dict]:
    """Produce the action list for building infrastructure."""
    return [
        {"action_type": "build_road_stop", "parameters": {
            "tile": stop_a, "length": 1, "is_truck": False, "on_drive_through": False,
        }},
        {"action_type": "build_road_stop", "parameters": {
            "tile": stop_b, "length": 1, "is_truck": False, "on_drive_through": False,
        }},
        {"action_type": "build_road_depot", "parameters": {"tile": depot_tile}},
    ]


def decide_buy_and_route(depot_tile: int, engine_id: int, vehicle_id: int, stop_a: int, stop_b: int) -> list[dict]:
    """Produce the action list for buying a bus and setting up its route."""
    return [
        {"action_type": "buy_vehicle", "parameters": {"depot_tile": depot_tile, "engine_id": engine_id}},
        {"action_type": "add_order", "parameters": {"vehicle_id": vehicle_id, "order_index": 0, "destination": stop_a}},
        {"action_type": "add_order", "parameters": {"vehicle_id": vehicle_id, "order_index": 1, "destination": stop_b}},
        {"action_type": "start_vehicle", "parameters": {"vehicle_id": vehicle_id}},
    ]


# ── Main loop: observe → decide → interpret → execute ─────────────────

async def main(base_url: str, session_id: str, company_id: int, poll_interval: float) -> None:
    session_url = f"{base_url}/sessions/{session_id}"

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        # Register as agent
        await client.post(f"{session_url}/agents/connect", json={
            "agent_id": "simple_bus", "name": "Simple Bus Agent", "company_scope": [company_id],
        })
        log.info("Connected to session %s as company %d", session_id, company_id)

        # Phase tracking
        town_a = town_b = None
        stop_a = stop_b = depot_tile = vehicle_id = None
        phase = "scout"

        while True:
            # ── Observe ──
            state = await observe_compact(client, session_url, company_id)
            log.info("date=%s  vehicles=%s  phase=%s",
                     state.get("game_date", "?"),
                     state.get("vehicles", {}).get("total", 0),
                     phase)

            # ── Decide & Interpret ──
            if phase == "scout":
                towns = await gs_query(client, session_url, "get_towns")
                if towns:
                    town_a, town_b = decide_scout(towns)
                    phase = "build"

            elif phase == "build":
                spots_a = await gs_query(client, session_url, "find_bus_stop_spots", {
                    "town_id": town_a["id"], "company_id": company_id, "max_results": 3,
                })
                spots_b = await gs_query(client, session_url, "find_bus_stop_spots", {
                    "town_id": town_b["id"], "company_id": company_id, "max_results": 3,
                })
                depot_spots = await gs_query(client, session_url, "find_depot_spots", {
                    "town_id": town_a["id"], "company_id": company_id, "max_results": 3,
                })

                if spots_a and spots_b and depot_spots:
                    stop_a = spots_a[0]["tile"]
                    stop_b = spots_b[0]["tile"]
                    depot_tile = depot_spots[0]["tile"]
                    actions = decide_build(stop_a, stop_b, depot_tile)
                    await interpret_actions(client, session_url, actions, company_id)
                    phase = "buy"
                else:
                    log.warning("Could not find spots — retrying next cycle")

            elif phase == "buy":
                engines = await gs_query(client, session_url, "get_engines", {
                    "company_id": company_id, "vehicle_type": 1,
                })
                buses = [e for e in engines if e.get("cargo_label") in ("PASS", "PASSENGERS", "")]
                if not buses:
                    buses = engines
                if buses:
                    # Buy first, then get vehicle ID, then set orders
                    buy_action = [{"action_type": "buy_vehicle", "parameters": {
                        "depot_tile": depot_tile, "engine_id": buses[0]["id"],
                    }}]
                    await interpret_actions(client, session_url, buy_action, company_id)

                    vehicles = await gs_query(client, session_url, "get_vehicles", {"company_id": company_id})
                    if vehicles:
                        vehicle_id = vehicles[-1]["id"]
                        route_actions = [
                            {"action_type": "add_order", "parameters": {
                                "vehicle_id": vehicle_id, "order_index": 0, "destination": stop_a,
                            }},
                            {"action_type": "add_order", "parameters": {
                                "vehicle_id": vehicle_id, "order_index": 1, "destination": stop_b,
                            }},
                            {"action_type": "start_vehicle", "parameters": {"vehicle_id": vehicle_id}},
                        ]
                        await interpret_actions(client, session_url, route_actions, company_id)
                        log.info("Bus route active: vehicle %d, %d <-> %d", vehicle_id, stop_a, stop_b)
                        phase = "monitor"

            elif phase == "monitor":
                company = state.get("company", {})
                vehicles_info = state.get("vehicles", {})
                log.info("  balance=%s  income=%s  vehicles=%d",
                         f"{company.get('balance', 0):,}",
                         f"{company.get('income', 0):,}",
                         vehicles_info.get("total", 0))

            await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple bus agent for nttd")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.session_id, args.company_id, args.poll_interval))
