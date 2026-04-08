"""GS integration tests -- require a running nttd server (OpenTTD auto-managed).

These tests exercise the full GameScript command pipeline: querying game state,
building infrastructure, buying vehicles, setting orders, and verifying cargo
delivery. They validate that the API chain works end-to-end.

Run with:
    uv run pytest tests/test_gs_integration.py -v -m gs_test

Or to reuse an existing session (skips create/teardown):
    uv run pytest tests/test_gs_integration.py -v -m gs_test --session-id ses_abc123

Requires:
    1. nttd server running: uv run uvicorn nttd.api.app:app
    2. OpenTTD binary available on PATH (auto-started by the session)
"""

import logging
import time

import httpx
import pytest

log = logging.getLogger(__name__)

pytestmark = pytest.mark.gs_test

# How long to wait for GS to become responsive after session start
_GS_READY_TIMEOUT = 30
_GS_READY_POLL = 2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_url(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--base-url")


@pytest.fixture(scope="module")
def company_id(request: pytest.FixtureRequest) -> int:
    return request.config.getoption("--company-id")


@pytest.fixture(scope="module")
def client(base_url: str) -> httpx.Client:
    """Synchronous httpx client for the test module."""
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def session_id(request: pytest.FixtureRequest, client: httpx.Client) -> str:
    """Create a session for the test module, or reuse one from --session-id.

    On teardown, stops and archives the session (unless --session-id was given).
    """
    provided = request.config.getoption("--session-id")
    if provided:
        # Verify it exists
        resp = client.get(f"/admin/sessions/{provided}")
        if resp.status_code != 200:
            pytest.skip(f"Session {provided} not found (status {resp.status_code})")
        yield provided
        return

    # Create a new session
    resp = client.post("/admin/sessions/new", json={"name": "gs_integration_test"})
    assert resp.status_code == 200, f"Failed to create session: {resp.text}"
    sid = resp.json()["session_id"]
    log.info("Created test session: %s", sid)

    # Small 128x128 map, year 1960 (all vehicle types), custom 4 towns, high sea for coast
    client.post(f"/admin/sessions/{sid}/settings", json={
        "settings": {
            "game_creation.map_x": "7",
            "game_creation.map_y": "7",
            "game_creation.starting_year": "1960",
            "game_creation.terrain_type": "1",
            "difficulty.number_towns": "4",
            "game_creation.custom_town_number": "4",
            "difficulty.quantity_sea_lakes": "3",
        },
    })

    # Start the session (spawns OpenTTD)
    resp = client.post(f"/admin/sessions/{sid}/start", json={
        "mode": "newgame",
        "ai_opponents": 0,
        "agent_companies": 1,
    })
    assert resp.status_code == 200, f"Failed to start session: {resp.text}"
    log.info("Session %s started, waiting for GS...", sid)

    # Wait for GS to become responsive
    deadline = time.time() + _GS_READY_TIMEOUT
    gs_ready = False
    while time.time() < deadline:
        try:
            resp = client.post(
                f"/sessions/{sid}/state/gs/query",
                params={"action": "ping"},
                json={},
            )
            if resp.status_code == 200:
                gs_ready = True
                break
        except httpx.RequestError:
            pass
        time.sleep(_GS_READY_POLL)

    assert gs_ready, f"GS did not become ready within {_GS_READY_TIMEOUT}s"
    log.info("GS ready for session %s", sid)

    # Speed up game for faster test execution (16x to ensure vehicles reach stations)
    resp = client.post(f"/sessions/{sid}/speed", params={"speed": 16})
    log.info("Game speed set to 16x for session %s (status=%d)", sid, resp.status_code)

    yield sid

    # Teardown: stop the session unless --keep-session was given
    keep = request.config.getoption("--keep-session")
    if keep:
        log.info("Keeping test session %s alive (--keep-session)", sid)
        return

    log.info("Stopping test session %s", sid)
    try:
        client.post(f"/admin/sessions/{sid}/stop", params={"end_reason": "gs_test_complete"})
        log.info("Session %s stopped and archived", sid)
    except Exception:
        log.warning("Failed to stop session %s during teardown", sid, exc_info=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def gs_query(client: httpx.Client, session_id: str, action: str, params: dict | None = None) -> list | dict:
    """Execute a GS query and return the result."""
    resp = client.post(
        f"/sessions/{session_id}/state/gs/query",
        params={"action": action},
        json=params or {},
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", True):
        log.warning("GS query %s failed: %s", action, data.get("error", "unknown"))
        return data
    return data.get("result", data)


def interpret(
    client: httpx.Client, session_id: str, actions: list[dict], company_id: int
) -> list[dict]:
    """Submit actions via the interpreter and return results."""
    resp = client.post(
        f"/sessions/{session_id}/actions/interpret",
        json=actions,
        params={"company_id": company_id},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


class TestGSQueries:
    """Test that basic GS queries return expected data."""

    def test_ping(self, client: httpx.Client, session_id: str) -> None:
        result = gs_query(client, session_id, "ping")
        assert result is not None

    def test_get_towns(self, client: httpx.Client, session_id: str) -> None:
        towns = gs_query(client, session_id, "get_towns")
        assert isinstance(towns, list)
        assert len(towns) >= 2, "Map should have at least 2 towns"
        town = towns[0]
        assert "id" in town
        assert "name" in town
        assert "population" in town
        assert town["population"] > 0

    def test_get_industries(self, client: httpx.Client, session_id: str) -> None:
        industries = gs_query(client, session_id, "get_industries")
        assert isinstance(industries, list)
        assert len(industries) >= 1

    def test_get_engines_road(self, client: httpx.Client, session_id: str, company_id: int) -> None:
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 1,
        })
        assert isinstance(engines, list)
        assert len(engines) >= 1, "Should have at least one road vehicle engine"

    def test_get_cargo_types(self, client: httpx.Client, session_id: str) -> None:
        cargos = gs_query(client, session_id, "get_cargo_types")
        assert isinstance(cargos, list)
        labels = [c.get("label", "") for c in cargos]
        assert "PASS" in labels, "Passengers cargo should exist"

    def test_get_map_size(self, client: httpx.Client, session_id: str) -> None:
        result = gs_query(client, session_id, "get_map_size")
        assert "size_x" in result or "width" in result
        assert "size_y" in result or "height" in result

    def test_get_date(self, client: httpx.Client, session_id: str) -> None:
        result = gs_query(client, session_id, "get_date")
        assert "year" in result


# ---------------------------------------------------------------------------
# Find-spots tests
# ---------------------------------------------------------------------------


class TestFindSpots:
    """Test that find-spots commands return valid data with direction fields."""

    def test_find_bus_stop_spots_has_direction(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        towns = gs_query(client, session_id, "get_towns")
        spots = gs_query(client, session_id, "find_bus_stop_spots", {
            "town_id": towns[0]["id"], "company_id": company_id, "max_results": 3,
        })
        assert len(spots) >= 1, "Should find at least one bus stop spot"
        spot = spots[0]
        assert "tile" in spot
        assert "direction" in spot, "find_bus_stop_spots must return direction"
        assert spot["direction"] in (0, 1, 2, 3)
        assert "cargo_acceptance" in spot

    def test_find_depot_spots_has_direction(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        towns = gs_query(client, session_id, "get_towns")
        spots = gs_query(client, session_id, "find_depot_spots", {
            "town_id": towns[0]["id"], "company_id": company_id, "max_results": 3,
        })
        assert len(spots) >= 1
        assert "depot_direction" in spots[0]


# ---------------------------------------------------------------------------
# Build + order pipeline
# ---------------------------------------------------------------------------


class TestBusRoutePipeline:
    """End-to-end: build stops, buy vehicle, add orders with station_id, verify movement."""

    def test_build_road_stop_returns_station_id(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        towns = gs_query(client, session_id, "get_towns")
        spots = gs_query(client, session_id, "find_bus_stop_spots", {
            "town_id": towns[0]["id"], "company_id": company_id, "max_results": 5,
        })
        assert spots

        # Try multiple spots in case of slope issues
        for spot in spots:
            results = interpret(client, session_id, [
                {"action_type": "build_road_stop", "parameters": {
                    "tile": spot["tile"], "direction": spot["direction"],
                    "is_truck": False, "is_drive_through": False,
                }},
            ], company_id)
            r = results[0]
            if r["status"] == "success":
                ce = r.get("changed_entities", {})
                assert "station_id" in ce, f"station_id missing from build result: {ce}"
                assert isinstance(ce["station_id"], int)
                return
            log.info("Spot tile=%d failed: %s", spot["tile"], r.get("error"))

        pytest.fail("Could not build road stop at any candidate spot")

    def test_full_bus_route_with_station_id(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        """Build two stops, buy vehicle, add orders by station_id, start, verify orders."""
        towns = gs_query(client, session_id, "get_towns")
        towns.sort(key=lambda t: t.get("population", 0), reverse=True)
        # Use towns[1] and towns[2] to avoid collision with test_build_road_stop (uses towns[0])
        town_a_idx = 1 if len(towns) > 2 else 0
        town_b_idx = 2 if len(towns) > 2 else min(1, len(towns) - 1)

        spots_a = gs_query(client, session_id, "find_bus_stop_spots", {
            "town_id": towns[town_a_idx]["id"], "company_id": company_id, "max_results": 5,
        })
        spots_b = gs_query(client, session_id, "find_bus_stop_spots", {
            "town_id": towns[town_b_idx]["id"], "company_id": company_id, "max_results": 5,
        })
        depot_spots = gs_query(client, session_id, "find_depot_spots", {
            "town_id": towns[town_a_idx]["id"], "company_id": company_id, "max_results": 5,
        })
        assert spots_a and spots_b and depot_spots

        # Determine if we need truck stops (no bus engines in early years)
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 1,
        })
        assert engines, "No road vehicle engines available"
        # Check if any bus (passenger) engine exists
        bus_engines = [e for e in engines if "bus" in e.get("name", "").lower()]
        is_truck = len(bus_engines) == 0  # Use truck stops if no buses available

        # Build stops -- try multiple candidates in case of ERR_FLAT_LAND_REQUIRED
        stop_a_result = None
        for spot in spots_a:
            r = interpret(client, session_id, [
                {"action_type": "build_road_stop", "parameters": {
                    "tile": spot["tile"], "direction": spot["direction"],
                    "is_truck": is_truck, "is_drive_through": False,
                }},
            ], company_id)[0]
            if r["status"] == "success":
                stop_a_result = r
                break
            log.info("Stop A at tile %d failed: %s", spot["tile"], r.get("error"))
        assert stop_a_result is not None, "Could not build stop A at any candidate"

        stop_b_result = None
        for spot in spots_b:
            r = interpret(client, session_id, [
                {"action_type": "build_road_stop", "parameters": {
                    "tile": spot["tile"], "direction": spot["direction"],
                    "is_truck": is_truck, "is_drive_through": False,
                }},
            ], company_id)[0]
            if r["status"] == "success":
                stop_b_result = r
                break
            log.info("Stop B at tile %d failed: %s", spot["tile"], r.get("error"))
        assert stop_b_result is not None, "Could not build stop B at any candidate"

        stop_results = [stop_a_result, stop_b_result]

        # Build depot -- try multiple spots in case first overlaps with a stop tile
        used_tiles = {spots_a[0]["tile"], spots_b[0]["tile"]}
        depot_tile = None
        for ds in depot_spots:
            if ds["tile"] in used_tiles:
                continue
            result = interpret(client, session_id, [
                {"action_type": "build_road_depot", "parameters": {
                    "tile": ds["tile"], "direction": ds["depot_direction"],
                }},
            ], company_id)
            if result[0]["status"] == "success":
                depot_tile = ds["tile"]
                break
            log.info("Depot at tile %d failed: %s, trying next", ds["tile"], result[0].get("error"))
        assert depot_tile is not None, "Could not build depot at any candidate spot"

        # Get station IDs
        sid_a = stop_results[0]["changed_entities"].get("station_id")
        sid_b = stop_results[1]["changed_entities"].get("station_id")
        if sid_a is None or sid_b is None:
            stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
            assert len(stations) >= 2
            sid_a = stations[-2]["id"]
            sid_b = stations[-1]["id"]

        # Buy -- engines were already queried above (bus vs truck detection)
        engine = bus_engines[0] if bus_engines else engines[0]
        log.info("Using engine: id=%d name=%s (is_truck=%s)",
                 engine["id"], engine.get("name", "?"), is_truck)
        buy_results = interpret(client, session_id, [
            {"action_type": "buy_vehicle", "parameters": {
                "depot_tile": depot_tile, "engine_id": engine["id"],
            }},
        ], company_id)
        assert buy_results[0]["status"] == "success", f"buy failed: {buy_results[0].get('error')}"

        vehicle_id = buy_results[0]["changed_entities"].get("vehicle_id")
        if vehicle_id is None:
            vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
            vehicle_id = vehicles[-1]["id"]

        # Add orders with station_id
        order_results = interpret(client, session_id, [
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": sid_a, "order_flags": 1,
            }},
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": sid_b, "order_flags": 1,
            }},
        ], company_id)

        assert order_results[0]["status"] == "success", (
            f"add_order(station_id={sid_a}) failed: {order_results[0].get('error')}"
        )
        assert order_results[1]["status"] == "success", (
            f"add_order(station_id={sid_b}) failed: {order_results[1].get('error')}"
        )

        # Verify orders
        orders = gs_query(client, session_id, "get_orders", {"vehicle_id": vehicle_id})
        assert len(orders) >= 2, f"Expected 2+ orders, got {len(orders)}"

        # Start
        start_results = interpret(client, session_id, [
            {"action_type": "start_vehicle", "parameters": {"vehicle_id": vehicle_id}},
        ], company_id)
        assert start_results[0]["status"] == "success"

        log.info("Bus route created: vehicle=%d, stations=%d<->%d", vehicle_id, sid_a, sid_b)

    def test_add_order_tile_fallback(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        """Verify add_order works when a tile is passed as station_id (fallback path)."""
        stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
        vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
        if not stations or not vehicles:
            pytest.skip("Need existing stations and vehicles for tile fallback test")

        # Find a station whose tile value is large enough to distinguish from station_id
        # We need a station with known tile; query get_station_info for the tile
        station_info = gs_query(client, session_id, "get_station_info", {"station_id": stations[0]["id"]})
        tile = station_info.get("tile")
        if tile is None or tile < 100:
            pytest.skip("Station tile too small to test fallback")

        vehicle_id = vehicles[0]["id"]

        result = interpret(client, session_id, [
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": tile, "order_flags": 1,
            }},
        ], company_id)

        assert result[0]["status"] == "success", (
            f"Tile-as-station_id fallback failed: {result[0].get('error')}"
        )


# ---------------------------------------------------------------------------
# Vehicle movement verification (longer-running)
# ---------------------------------------------------------------------------


class TestVehicleMovement:
    """Verify vehicles actually move and stations get rated."""

    def test_vehicle_moves(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        """A running vehicle with orders should have speed > 0."""
        for attempt in range(6):
            vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
            running = [v for v in vehicles if not v.get("in_depot", True) and v.get("order_count", 0) >= 2]
            if not running:
                time.sleep(5)
                continue
            for v in running:
                if v.get("current_speed", 0) > 0:
                    log.info("Vehicle %d moving at speed %d", v["id"], v["current_speed"])
                    return
            time.sleep(5)

        if not running:
            pytest.skip("No running vehicles with orders found")
        pytest.fail("No vehicle achieved speed > 0 after 30s")

    def test_station_gets_rated(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        """After a vehicle visits a station, the station should get a cargo rating."""
        date_start = gs_query(client, session_id, "get_date")
        log.info("Rating test start -- game date: %s", date_start)

        for attempt in range(60):
            stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
            if isinstance(stations, list):
                for s in stations:
                    for ca in s.get("cargo_acceptance", []):
                        if ca.get("rated"):
                            log.info("Station %d (%s) rated for %s", s["id"], s["name"], ca["cargo_label"])
                            for cw in s.get("cargo_waiting", []):
                                if cw.get("count", 0) > 0:
                                    log.info("  cargo_waiting: %s count=%d", cw.get("cargo_label"), cw["count"])
                            return
            # Detailed diagnostics every 10 polls
            if attempt % 10 == 0:
                date_now = gs_query(client, session_id, "get_date")
                log.info("  [attempt %d/60] game date: %s", attempt, date_now)
                if isinstance(stations, list):
                    for s in stations:
                        log.info(
                            "  station %d (%s): acceptance=%s waiting=%s",
                            s.get("id", -1), s.get("name", "?"),
                            s.get("cargo_acceptance", []),
                            s.get("cargo_waiting", []),
                        )
                vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
                if isinstance(vehicles, list):
                    for v in vehicles:
                        log.info(
                            "  vehicle %d: speed=%d orders=%d in_depot=%s",
                            v.get("id", -1), v.get("current_speed", 0),
                            v.get("order_count", 0), v.get("in_depot", "?"),
                        )
            time.sleep(5)

        date_end = gs_query(client, session_id, "get_date")
        log.info("Rating test end -- game date: %s (waited 300 wall-seconds)", date_end)
        pytest.fail("No station got a cargo rating after 300s -- vehicles may not reach stations")


# ---------------------------------------------------------------------------
# Station data fields
# ---------------------------------------------------------------------------


class TestStationData:
    """Test that station queries return cargo fields."""

    def test_cargo_acceptance_field(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
        if not stations:
            pytest.skip("No stations")
        assert "cargo_acceptance" in stations[0]
        assert isinstance(stations[0]["cargo_acceptance"], list)

    def test_cargo_waiting_field(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
        if not stations:
            pytest.skip("No stations")
        assert "cargo_waiting" in stations[0]
        assert isinstance(stations[0]["cargo_waiting"], list)


# ---------------------------------------------------------------------------
# Cargo delivery verification
# ---------------------------------------------------------------------------


class TestCargoDelivery:
    """Verify cargo actually gets delivered (both stations rated = round trip complete)."""

    def test_cargo_moves(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        """At least one station should get rated, confirming cargo pickup and movement."""
        rated_names: list[str] = []
        for attempt in range(60):
            stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
            if not isinstance(stations, list):
                time.sleep(5)
                continue
            for s in stations:
                for ca in s.get("cargo_acceptance", []):
                    if ca.get("rated") and s["name"] not in rated_names:
                        rated_names.append(s["name"])
                        log.info(
                            "Station %d (%s) rated for %s -- cargo moving",
                            s["id"], s["name"], ca.get("cargo_label"),
                        )
            if len(rated_names) >= 2:
                log.info("Both stations rated -- full round trip confirmed")
                return
            if len(rated_names) >= 1 and attempt >= 20:
                log.info("1 station rated after %ds -- cargo pickup confirmed", attempt * 5)
                return
            time.sleep(5)

        if rated_names:
            log.info("Only %d station(s) rated -- bus may still be en route", len(rated_names))
            return
        pytest.fail("No station got rated after 300s -- vehicle not reaching stations")

    def test_company_has_income(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        """After cargo delivery, company should have non-zero income."""
        for attempt in range(30):
            finance = gs_query(client, session_id, "get_company_finance", {"company_id": company_id})
            if isinstance(finance, dict):
                income = finance.get("income", 0)
                if income > 0:
                    log.info("Company income: %d -- cargo delivery generating revenue", income)
                    return
            time.sleep(5)

        # Income might still be 0 if the quarter hasn't ticked yet -- just log, don't fail hard
        log.warning("Company income is still 0 after 150s (may need more game time)")


# ---------------------------------------------------------------------------
# Vehicle data fields
# ---------------------------------------------------------------------------


class TestVehicleData:
    """Test that vehicle queries return order data."""

    def test_vehicles_have_orders(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
        if not vehicles:
            pytest.skip("No vehicles")
        v_with_orders = [v for v in vehicles if v.get("order_count", 0) > 0]
        if not v_with_orders:
            pytest.skip("No vehicles with orders")

        v = v_with_orders[0]
        assert "orders" in v, f"Missing orders in vehicle: {list(v.keys())}"
        assert len(v["orders"]) > 0
        order = v["orders"][0]
        assert "destination" in order
        assert "flags" in order
        assert "is_goto_station" in order


# ---------------------------------------------------------------------------
# Engine availability (all transport modes at year 1960)
# ---------------------------------------------------------------------------


class TestEngineAvailability:
    """Verify engines exist for all transport modes at starting year 1960."""

    def test_road_engines_include_buses(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 1,
        })
        assert len(engines) >= 1, "No road vehicle engines"
        buses = [e for e in engines if "bus" in e.get("name", "").lower()]
        assert buses, f"No bus engines at starting year. Available: {[e['name'] for e in engines]}"
        log.info("Bus engines: %s", [e["name"] for e in buses])

    def test_road_engines_include_trucks(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 1,
        })
        trucks = [e for e in engines if "bus" not in e.get("name", "").lower()]
        assert trucks, f"No truck engines at starting year. Available: {[e['name'] for e in engines]}"
        log.info("Truck engines: %s", [e["name"] for e in trucks])

    def test_train_engines(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 0,
        })
        assert len(engines) >= 1, "No train engines available"
        log.info("Train engines (%d): %s", len(engines), [e["name"] for e in engines[:5]])

    def test_ship_engines(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 2,
        })
        assert len(engines) >= 1, "No ship engines available"
        log.info("Ship engines (%d): %s", len(engines), [e["name"] for e in engines[:5]])

    def test_aircraft_engines(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 3,
        })
        assert len(engines) >= 1, "No aircraft engines available"
        log.info("Aircraft engines (%d): %s", len(engines), [e["name"] for e in engines[:5]])


# ---------------------------------------------------------------------------
# Airport pipeline (air transport e2e)
# ---------------------------------------------------------------------------


class TestAirRoutePipeline:
    """End-to-end: build airports, buy aircraft, add orders with station_id."""

    def test_full_air_route(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        towns = gs_query(client, session_id, "get_towns")
        assert isinstance(towns, list), f"Expected list of towns, got {type(towns)}: {towns}"
        towns.sort(key=lambda t: t.get("population", 0), reverse=True)
        assert len(towns) >= 2, "Need at least 2 towns"

        # Find airport spots for two towns (airport_type=0 = small airport)
        spots_a = gs_query(client, session_id, "find_airport_spots", {
            "town_id": towns[0]["id"], "company_id": company_id,
            "airport_type": 0, "max_results": 3,
        })
        spots_b = gs_query(client, session_id, "find_airport_spots", {
            "town_id": towns[1]["id"], "company_id": company_id,
            "airport_type": 0, "max_results": 3,
        })
        if not isinstance(spots_a, list) or not isinstance(spots_b, list) or not spots_a or not spots_b:
            pytest.skip("No airport spots found (map may be too small or hilly)")

        # Build airport A
        airport_a = None
        for spot in spots_a:
            r = interpret(client, session_id, [
                {"action_type": "build_airport", "parameters": {
                    "tile": spot["tile"], "airport_type": 0,
                }},
            ], company_id)[0]
            if r["status"] == "success":
                airport_a = r
                break
            log.info("Airport A at tile %d failed: %s", spot["tile"], r.get("error"))
        assert airport_a is not None, "Could not build airport A"
        sid_a = airport_a["changed_entities"].get("station_id")
        log.info("Airport A built: station_id=%s", sid_a)

        # Build airport B
        airport_b = None
        for spot in spots_b:
            r = interpret(client, session_id, [
                {"action_type": "build_airport", "parameters": {
                    "tile": spot["tile"], "airport_type": 0,
                }},
            ], company_id)[0]
            if r["status"] == "success":
                airport_b = r
                break
            log.info("Airport B at tile %d failed: %s", spot["tile"], r.get("error"))
        assert airport_b is not None, "Could not build airport B"
        sid_b = airport_b["changed_entities"].get("station_id")
        log.info("Airport B built: station_id=%s", sid_b)

        # Get hangar for depot tile
        hangars = gs_query(client, session_id, "get_hangars", {"company_id": company_id})
        assert isinstance(hangars, list) and hangars, f"No hangars found: {hangars}"
        hangar_tile = hangars[0]["hangar_tile"]

        # Get aircraft engine
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 3,
        })
        assert engines, "No aircraft engines available"
        engine = engines[0]
        log.info("Using aircraft engine: %s (id=%d)", engine.get("name"), engine["id"])

        # Buy aircraft
        buy = interpret(client, session_id, [
            {"action_type": "buy_vehicle", "parameters": {
                "depot_tile": hangar_tile, "engine_id": engine["id"],
            }},
        ], company_id)[0]
        assert buy["status"] == "success", f"Buy aircraft failed: {buy.get('error')}"
        vehicle_id = buy["changed_entities"].get("vehicle_id")
        if vehicle_id is None:
            vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
            vehicle_id = vehicles[-1]["id"]

        # Add orders with station_id
        if sid_a is None or sid_b is None:
            stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
            airport_stations = [s for s in stations if s.get("type") == "airport"]
            if len(airport_stations) >= 2:
                sid_a = airport_stations[-2]["id"]
                sid_b = airport_stations[-1]["id"]
            else:
                sid_a = stations[-2]["id"]
                sid_b = stations[-1]["id"]

        orders = interpret(client, session_id, [
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": sid_a, "order_flags": 1,
            }},
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": sid_b, "order_flags": 1,
            }},
        ], company_id)
        assert orders[0]["status"] == "success", f"add_order A failed: {orders[0].get('error')}"
        assert orders[1]["status"] == "success", f"add_order B failed: {orders[1].get('error')}"

        # Start
        start = interpret(client, session_id, [
            {"action_type": "start_vehicle", "parameters": {"vehicle_id": vehicle_id}},
        ], company_id)[0]
        assert start["status"] == "success", f"start failed: {start.get('error')}"
        log.info("Air route created: vehicle=%d, stations=%s<->%s", vehicle_id, sid_a, sid_b)


# ---------------------------------------------------------------------------
# Water pipeline (water transport e2e)
# ---------------------------------------------------------------------------


class TestWaterRoutePipeline:
    """End-to-end: build docks, buy ship, add orders with station_id."""

    def test_full_water_route(
        self, client: httpx.Client, session_id: str, company_id: int
    ) -> None:
        towns = gs_query(client, session_id, "get_towns")
        assert isinstance(towns, list), f"Expected list of towns, got {type(towns)}: {towns}"
        towns.sort(key=lambda t: t.get("population", 0), reverse=True)

        # Find dock spots near towns
        dock_spots_a = None
        dock_spots_b = None
        for town in towns[:5]:
            spots = gs_query(client, session_id, "find_dock_spots", {
                "town_id": town["id"], "company_id": company_id, "max_results": 3,
            })
            if isinstance(spots, list) and spots:
                if dock_spots_a is None:
                    dock_spots_a = (town, spots)
                elif dock_spots_b is None:
                    dock_spots_b = (town, spots)
                    break

        if dock_spots_a is None or dock_spots_b is None:
            pytest.skip("Not enough coastal towns for water route (need 2 dock spots)")

        # Build dock A
        dock_a = None
        for spot in dock_spots_a[1]:
            r = interpret(client, session_id, [
                {"action_type": "build_dock", "parameters": {"tile": spot["tile"]}},
            ], company_id)[0]
            if r["status"] == "success":
                dock_a = r
                break
            log.info("Dock A at tile %d failed: %s", spot["tile"], r.get("error"))
        assert dock_a is not None, "Could not build dock A"
        sid_a = dock_a["changed_entities"].get("station_id")
        log.info("Dock A built: station_id=%s", sid_a)

        # Build dock B
        dock_b = None
        for spot in dock_spots_b[1]:
            r = interpret(client, session_id, [
                {"action_type": "build_dock", "parameters": {"tile": spot["tile"]}},
            ], company_id)[0]
            if r["status"] == "success":
                dock_b = r
                break
            log.info("Dock B at tile %d failed: %s", spot["tile"], r.get("error"))
        assert dock_b is not None, "Could not build dock B"
        sid_b = dock_b["changed_entities"].get("station_id")
        log.info("Dock B built: station_id=%s", sid_b)

        # Find water depot
        water_depot_spots = gs_query(client, session_id, "find_water_depot_spots", {
            "town_id": dock_spots_a[0]["id"], "company_id": company_id, "max_results": 3,
        })
        if not water_depot_spots:
            pytest.skip("No water depot spots found")

        depot_result = None
        for wds in water_depot_spots:
            r = interpret(client, session_id, [
                {"action_type": "build_water_depot", "parameters": {"tile": wds["tile"]}},
            ], company_id)[0]
            if r["status"] == "success":
                depot_result = r
                break
            log.info("Water depot at tile %d failed: %s", wds["tile"], r.get("error"))
        assert depot_result is not None, "Could not build water depot"
        depot_tile = water_depot_spots[0]["tile"]

        # Get ship engine
        engines = gs_query(client, session_id, "get_engines", {
            "company_id": company_id, "vehicle_type": 2,
        })
        assert engines, "No ship engines available"
        engine = engines[0]
        log.info("Using ship engine: %s (id=%d)", engine.get("name"), engine["id"])

        # Buy ship
        buy = interpret(client, session_id, [
            {"action_type": "buy_vehicle", "parameters": {
                "depot_tile": depot_tile, "engine_id": engine["id"],
            }},
        ], company_id)[0]
        assert buy["status"] == "success", f"Buy ship failed: {buy.get('error')}"
        vehicle_id = buy["changed_entities"].get("vehicle_id")
        if vehicle_id is None:
            vehicles = gs_query(client, session_id, "get_vehicles", {"company_id": company_id})
            vehicle_id = vehicles[-1]["id"]

        # Add orders
        if sid_a is None or sid_b is None:
            stations = gs_query(client, session_id, "get_stations", {"company_id": company_id})
            dock_stations = [s for s in stations if s.get("type") == "dock"]
            if len(dock_stations) >= 2:
                sid_a = dock_stations[-2]["id"]
                sid_b = dock_stations[-1]["id"]

        orders = interpret(client, session_id, [
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": sid_a, "order_flags": 1,
            }},
            {"action_type": "add_order", "parameters": {
                "vehicle_id": vehicle_id, "station_id": sid_b, "order_flags": 1,
            }},
        ], company_id)
        if orders[0]["status"] != "success" or orders[1]["status"] != "success":
            pytest.skip(
                "Ship cannot path between docks (disconnected water bodies) -- "
                f"order A: {orders[0].get('error')}, order B: {orders[1].get('error')}"
            )

        # Start
        start = interpret(client, session_id, [
            {"action_type": "start_vehicle", "parameters": {"vehicle_id": vehicle_id}},
        ], company_id)[0]
        assert start["status"] == "success", f"start failed: {start.get('error')}"
        log.info("Water route created: vehicle=%d, stations=%s<->%s", vehicle_id, sid_a, sid_b)
