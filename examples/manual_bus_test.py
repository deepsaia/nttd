#!/usr/bin/env python3
"""Manual end-to-end bus route test.

Validates the full pipeline: find spots -> build stops -> buy vehicle ->
add orders -> start -> verify cargo delivery.

Requires a running nttd session. Either pass --session-id for an existing
session, or omit it to create a new one.

Usage:
    uv run python examples/manual_bus_test.py --session-id ses_abc123
    uv run python examples/manual_bus_test.py  # creates a new session
"""

import argparse
import asyncio
import json
import logging
import sys
import time

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bus_test")


async def gs_query(
    client: httpx.AsyncClient, session_url: str, action: str, params: dict | None = None
) -> dict | list:
    """Run a GS query and return the result."""
    resp = await client.post(
        f"{session_url}/state/gs/query", params={"action": action}, json=params or {}
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", data)


async def interpret(
    client: httpx.AsyncClient,
    session_url: str,
    actions: list[dict],
    company_id: int,
) -> list[dict]:
    """Submit actions via the interpreter endpoint."""
    resp = await client.post(
        f"{session_url}/actions/interpret",
        json=actions,
        params={"company_id": company_id},
    )
    resp.raise_for_status()
    return resp.json()


def check(label: str, condition: bool, detail: str = "") -> None:
    """Assert a step passed, log and exit on failure."""
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" -- {detail}"
    if condition:
        log.info(msg)
    else:
        log.error(msg)
        sys.exit(1)


async def run_test(base_url: str, session_id: str, company_id: int) -> None:
    session_url = f"{base_url}/sessions/{session_id}"

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        # ── Step 1: Get towns ─────────────────────────────────────────
        log.info("Step 1: Get towns")
        towns = await gs_query(client, session_url, "get_towns")
        check("got towns", isinstance(towns, list) and len(towns) >= 2, f"{len(towns)} towns")
        towns.sort(key=lambda t: t.get("population", 0), reverse=True)
        town_a, town_b = towns[0], towns[1]
        log.info("  Town A: %s (pop %d), Town B: %s (pop %d)",
                 town_a["name"], town_a["population"], town_b["name"], town_b["population"])

        # ── Step 2: Find bus stop spots ───────────────────────────────
        log.info("Step 2: Find bus stop spots")
        spots_a = await gs_query(client, session_url, "find_bus_stop_spots", {
            "town_id": town_a["id"], "company_id": company_id, "max_results": 5,
        })
        check("spots for town A", len(spots_a) > 0, f"{len(spots_a)} spots")
        check("direction field present", "direction" in spots_a[0],
              f"keys: {list(spots_a[0].keys())}")

        spots_b = await gs_query(client, session_url, "find_bus_stop_spots", {
            "town_id": town_b["id"], "company_id": company_id, "max_results": 5,
        })
        check("spots for town B", len(spots_b) > 0, f"{len(spots_b)} spots")

        spot_a = spots_a[0]
        spot_b = spots_b[0]
        log.info("  Spot A: tile=%d dir=%d cargo=%s",
                 spot_a["tile"], spot_a["direction"],
                 [c["cargo_label"] for c in spot_a.get("cargo_acceptance", [])])
        log.info("  Spot B: tile=%d dir=%d cargo=%s",
                 spot_b["tile"], spot_b["direction"],
                 [c["cargo_label"] for c in spot_b.get("cargo_acceptance", [])])

        # ── Step 3: Find depot spot ───────────────────────────────────
        log.info("Step 3: Find depot spot")
        depot_spots = await gs_query(client, session_url, "find_depot_spots", {
            "town_id": town_a["id"], "company_id": company_id, "max_results": 3,
        })
        check("depot spots found", len(depot_spots) > 0, f"{len(depot_spots)} spots")
        depot_spot = depot_spots[0]
        log.info("  Depot: tile=%d dir=%d", depot_spot["tile"], depot_spot["depot_direction"])

        # ── Step 4: Build infrastructure ──────────────────────────────
        log.info("Step 4: Build bus stops and depot")
        build_results = await interpret(client, session_url, [
            {"action_type": "build_road_stop", "parameters": {
                "tile": spot_a["tile"], "direction": spot_a["direction"],
                "is_truck": False, "is_drive_through": False,
            }},
            {"action_type": "build_road_stop", "parameters": {
                "tile": spot_b["tile"], "direction": spot_b["direction"],
                "is_truck": False, "is_drive_through": False,
            }},
            {"action_type": "build_road_depot", "parameters": {
                "tile": depot_spot["tile"], "direction": depot_spot["depot_direction"],
            }},
        ], company_id)

        stop_a_result = build_results[0]
        stop_b_result = build_results[1]
        depot_result = build_results[2]
        check("stop A built", stop_a_result["status"] == "success",
              json.dumps(stop_a_result.get("changed_entities", stop_a_result.get("error", ""))))
        check("stop B built", stop_b_result["status"] == "success",
              json.dumps(stop_b_result.get("changed_entities", stop_b_result.get("error", ""))))
        check("depot built", depot_result["status"] == "success",
              json.dumps(depot_result.get("changed_entities", depot_result.get("error", ""))))

        # Extract station_ids from build results
        stop_a_sid = stop_a_result.get("changed_entities", {}).get("station_id")
        stop_b_sid = stop_b_result.get("changed_entities", {}).get("station_id")
        log.info("  Stop A station_id=%s, Stop B station_id=%s", stop_a_sid, stop_b_sid)

        # Fallback: get station IDs from get_stations if not in build result
        if stop_a_sid is None or stop_b_sid is None:
            log.info("  station_id not in build result, querying get_stations...")
            stations = await gs_query(client, session_url, "get_stations", {
                "company_id": company_id,
            })
            log.info("  Found %d stations: %s", len(stations),
                     [(s["id"], s["name"]) for s in stations])
            if len(stations) >= 2:
                stop_a_sid = stations[0]["id"]
                stop_b_sid = stations[1]["id"]
        check("have station IDs", stop_a_sid is not None and stop_b_sid is not None,
              f"A={stop_a_sid}, B={stop_b_sid}")

        # ── Step 5: Get engines ───────────────────────────────────────
        log.info("Step 5: Get bus engines")
        engines = await gs_query(client, session_url, "get_engines", {
            "company_id": company_id, "vehicle_type": 1,
        })
        buses = [e for e in engines if e.get("cargo_label") in ("PASS", "")]
        if not buses:
            buses = engines
        check("engines available", len(buses) > 0, f"{len(buses)} bus engines")
        engine_id = buses[0]["id"]
        log.info("  Using engine: id=%d name=%s", engine_id, buses[0].get("name", "?"))

        # ── Step 6: Buy vehicle ───────────────────────────────────────
        log.info("Step 6: Buy vehicle")
        buy_results = await interpret(client, session_url, [
            {"action_type": "buy_vehicle", "parameters": {
                "depot_tile": depot_spot["tile"], "engine_id": engine_id,
            }},
        ], company_id)
        check("vehicle bought", buy_results[0]["status"] == "success",
              json.dumps(buy_results[0].get("changed_entities", buy_results[0].get("error", ""))))

        # Get vehicle ID
        vehicles = await gs_query(client, session_url, "get_vehicles", {
            "company_id": company_id,
        })
        check("vehicle exists", len(vehicles) > 0)
        vehicle_id = vehicles[-1]["id"]
        log.info("  Vehicle id=%d name=%s", vehicle_id, vehicles[-1].get("name", "?"))

        # ── Step 7: Add orders ────────────────────────────────────────
        log.info("Step 7: Add orders (station_id=%d, station_id=%d)", stop_a_sid, stop_b_sid)
        order_results = await interpret(client, session_url, [
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": stop_a_sid, "order_flags": 1,
            }},
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": stop_b_sid, "order_flags": 1,
            }},
        ], company_id)
        check("order 1 added", order_results[0]["status"] == "success",
              json.dumps(order_results[0].get("error", "")))
        check("order 2 added", order_results[1]["status"] == "success",
              json.dumps(order_results[1].get("error", "")))

        # Verify orders via get_orders
        orders = await gs_query(client, session_url, "get_orders", {
            "vehicle_id": vehicle_id,
        })
        log.info("  Orders: %s", json.dumps(orders))
        check("2 orders set", len(orders) >= 2, f"got {len(orders)} orders")

        # ── Step 8: Start vehicle ─────────────────────────────────────
        log.info("Step 8: Start vehicle")
        start_results = await interpret(client, session_url, [
            {"action_type": "start_vehicle", "parameters": {"vehicle_id": vehicle_id}},
        ], company_id)
        check("vehicle started", start_results[0]["status"] == "success")

        # ── Step 9: Monitor for cargo delivery ────────────────────────
        log.info("Step 9: Monitoring for 90 seconds...")
        start_time = time.time()
        cargo_delivered = False

        while time.time() - start_time < 90:
            await asyncio.sleep(10)
            elapsed = int(time.time() - start_time)

            # Check vehicle
            vehicles = await gs_query(client, session_url, "get_vehicles", {
                "company_id": company_id,
            })
            v = next((x for x in vehicles if x["id"] == vehicle_id), None)
            if v:
                log.info("  [%ds] Vehicle speed=%d in_depot=%s profit=%d orders=%d",
                         elapsed, v.get("current_speed", 0), v.get("in_depot", "?"),
                         v.get("profit_this_year", 0), v.get("order_count", 0))

            # Check stations
            stations = await gs_query(client, session_url, "get_stations", {
                "company_id": company_id,
            })
            for s in stations:
                rated_cargos = [c for c in s.get("cargo_acceptance", []) if c.get("rated")]
                waiting_cargos = [c for c in s.get("cargo_waiting", []) if c.get("waiting", 0) > 0]
                if rated_cargos or waiting_cargos:
                    log.info("  [%ds] Station %d (%s): rated=%s waiting=%s",
                             elapsed, s["id"], s["name"],
                             [c["cargo_label"] for c in rated_cargos],
                             [(c["cargo_label"], c["waiting"]) for c in waiting_cargos])
                    cargo_delivered = True

        # ── Final verdict ─────────────────────────────────────────────
        log.info("=" * 60)
        if cargo_delivered:
            log.info("SUCCESS: Cargo is flowing! Stations got rated and/or have waiting cargo.")
        else:
            log.error("FAIL: No cargo delivery detected after 90 seconds.")
            log.error("  Possible causes:")
            log.error("  - Vehicle can't reach station (road connectivity issue)")
            log.error("  - Station not in town catchment area")
            log.error("  - Game paused or speed too slow")
            sys.exit(1)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Manual bus route end-to-end test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True, help="Existing session ID")
    parser.add_argument("--company-id", type=int, default=0)
    args = parser.parse_args()

    await run_test(args.base_url, args.session_id, args.company_id)


if __name__ == "__main__":
    asyncio.run(main())
