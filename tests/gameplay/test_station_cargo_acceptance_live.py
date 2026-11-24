"""Station queries must report the game's airport acceptance, not one anchor tile.

Run against an isolated local nttd API with ``-m gs_test --base-url ...``.
The fixture creates and stops its own seed-1 world; it does not use a live run.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator

import httpx
import pytest

from tests.gameplay.test_gs_integration import gs_query, interpret

pytestmark = pytest.mark.gs_test

_ADMIN = "/v1/operator/admin/sessions"
_PLAY = "/v1/participant/sessions"
_SCENARIO = """
scenario {
  name = "airport-acceptance-regression"
  objective = "global"
  map { size_x = 256, size_y = 256, terrain_type = "flat", seed = 1 }
  companies { num_ai_companies = 0, competitors_interval = 0, max_loan = 300000 }
  runtime { mode = "async_realtime", snapshot_interval_days = 1 }
  heartbeat { interval_days = 1, action_window_seconds = 5.0 }
  end_conditions {
    logic = "any"
    time_limit { enabled = true, wall_minutes = 3.0 }
    max_heartbeats { enabled = false, count = 366 }
    bankruptcy { enabled = true }
  }
  scored = false
}
"""


@pytest.fixture(scope="module")
def airport_world(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[httpx.Client, str]]:
    config = tmp_path_factory.mktemp("airport_acceptance") / "scenario.conf"
    config.write_text(_SCENARIO)
    sid = f"airport_acceptance_{uuid.uuid4().hex[:12]}"
    with httpx.Client(base_url=request.config.getoption("--base-url"), timeout=45) as client:
        response = client.post(f"{_ADMIN}/new", json={"name": sid, "config_path": str(config)})
        response.raise_for_status()
        try:
            # Match the experimental world's company setup. This company has no
            # autonomous AI script; all construction below is explicit.
            response = client.post(
                f"{_ADMIN}/{sid}/start",
                json={"mode": "newgame", "agent_companies": 0, "ai_opponents": 1},
            )
            response.raise_for_status()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                response = client.get(f"{_PLAY}/{sid}/state/full")
                if response.is_success and response.json().get("companies"):
                    break
                time.sleep(0.25)
            else:
                pytest.fail("The test company's game state did not become ready")
            yield client, sid
        finally:
            response = client.post(f"{_ADMIN}/{sid}/stop")
            response.raise_for_status()


def _build_airport(client: httpx.Client, sid: str, x: int, y: int) -> int:
    result = interpret(client, sid, [{
        "action_type": "build_airport",
        "parameters": {"x": x, "y": y, "airport_type": 1},
    }], 0)[0]
    assert result["status"] == "success", result
    return result["changed_entities"]["station_id"]


def _assert_passenger_acceptance(
    client: httpx.Client, sid: str, station_id: int, expected: bool,
) -> None:
    stations = gs_query(client, sid, "get_stations")
    station = next(s for s in stations if s["id"] == station_id)
    detail = gs_query(client, sid, "get_station_info", {"station_id": station_id})
    # The full snapshot refreshes on the game's heartbeat, while direct queries
    # above are immediate. Wait only for the newly built station to appear.
    deadline = time.monotonic() + 10
    while True:
        response = client.get(f"{_PLAY}/{sid}/state/full")
        response.raise_for_status()
        snapshot_station = next((
            s for s in response.json()["stations"] if s["id"] == station_id
        ), None)
        if snapshot_station is not None:
            break
        assert time.monotonic() < deadline, "New station missing from the full snapshot"
        time.sleep(0.25)
    for view in (station, detail, snapshot_station):
        passengers = next((c for c in view["cargo_acceptance"] if c["cargo_label"] == "PASS"), None)
        assert bool(passengers and passengers["accepts"]) is expected, view
        assert all(c["supply_is_estimate"] is True for c in view["cargo_acceptance"]), view


def test_large_airport_acceptance_includes_houses_away_from_its_anchor(
    airport_world: tuple[httpx.Client, str],
) -> None:
    client, sid = airport_world
    towns = gs_query(client, sid, "get_towns")
    assert any(t["id"] == 15 and t["name"] == "Planinghall" for t in towns), towns
    sites = gs_query(client, sid, "find_airport_spots", {
        "town_id": 15, "airport_type": 1, "radius": 15, "max_results": 500,
    })
    site = next(s for s in sites if (s["x"], s["y"]) == (181, 203))
    assert site["width"] == site["height"] == 6
    assert site["within_coverage"] is True, site
    assert any(c["cargo_label"] == "PASS" and c["acceptance"] >= 8 for c in site["cargo_acceptance"])
    # This exact 6x6 site triggered the false "no passenger acceptance"
    # diagnosis: its north-west anchor is outside the relevant houses' range.
    station_id = _build_airport(client, sid, 181, 203)
    _assert_passenger_acceptance(client, sid, station_id, True)


def test_airport_without_passenger_catchment_is_not_reported_as_accepting(
    airport_world: tuple[httpx.Client, str],
) -> None:
    client, sid = airport_world
    candidates = gs_query(client, sid, "find_airport_spots", {
        "town_id": 15, "airport_type": 1, "radius": 30, "max_results": 500,
    })
    empty = [spot for spot in candidates if not any(
        c["cargo_label"] == "PASS" and c.get("acceptance", 0) >= 8
        for c in spot["cargo_acceptance"]
    )]
    assert empty, "The regression map must offer a site without passenger acceptance"
    spot = empty[0]
    station_id = _build_airport(client, sid, spot["x"], spot["y"])
    _assert_passenger_acceptance(client, sid, station_id, False)
