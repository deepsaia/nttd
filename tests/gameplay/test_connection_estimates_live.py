"""Connection estimates must price a feasible build without changing the map."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.gameplay.test_gs_integration import gs_query, interpret
from tests.gameplay.test_station_cargo_acceptance_live import airport_world as airport_world

pytestmark = pytest.mark.gs_test


@pytest.fixture(scope="module")
def estimate_world(airport_world: tuple[httpx.Client, str]) -> tuple[httpx.Client, str]:
    """Use an isolated company without vehicles or loan interest."""
    client, sid = airport_world
    response = client.post(
        f"/v1/operator/admin/sessions/{sid}/deity/change_balance",
        json={"company_id": 0, "delta": 100_000},
    )
    response.raise_for_status()
    result = interpret(client, sid, [{
        "action_type": "set_loan", "parameters": {"amount": 0},
    }], 0)[0]
    assert result["status"] == "success", result
    return client, sid


def _tiles(client: httpx.Client, sid: str, bounds: dict[str, int]) -> list[dict[str, Any]]:
    result = gs_query(client, sid, "get_tile_area", bounds)
    assert isinstance(result, list), result
    return result


def _clear_corridor(client: httpx.Client, sid: str) -> dict[str, int]:
    """Find six flat, empty tiles without trees or existing infrastructure."""
    for origin in (32, 64, 96, 128, 160, 192):
        bounds = {"x1": origin, "y1": 32, "x2": origin + 19, "y2": 51}
        tiles = _tiles(client, sid, bounds)
        available = {
            (tile["x"], tile["y"]): tile for tile in tiles
            if tile["buildable"] and tile["slope"] == 0
            and not any(tile[key] for key in (
                "has_tree", "has_road", "has_rail", "water", "coast", "is_station",
            ))
        }
        for x, y in sorted(available):
            points = [available.get((x + offset, y)) for offset in range(6)]
            if all(point is not None for point in points):
                heights = {point["height"] for point in points if point is not None}
                if len(heights) == 1:
                    return {"x1": x, "y1": y, "x2": x + 5, "y2": y}
    pytest.fail("The regression map has no empty flat corridor")


def _money(client: httpx.Client, sid: str) -> int:
    result = gs_query(client, sid, "get_company_finance", {"company_id": 0})
    assert isinstance(result, dict), result
    return int(result["balance"])


def _estimate(
    client: httpx.Client, sid: str, action: str, parameters: dict[str, int],
) -> dict[str, Any]:
    return interpret(client, sid, [{
        "action_type": "estimate_cost",
        "parameters": {"action": action, "params": parameters},
    }], 0)[0]


@pytest.mark.parametrize("action", ["connect_rail", "connect_road"])
def test_connection_estimate_prices_build_without_changing_tiles(
    estimate_world: tuple[httpx.Client, str], action: str,
) -> None:
    client, sid = estimate_world
    bounds = _clear_corridor(client, sid)
    parameters = {
        "from_x": bounds["x1"], "from_y": bounds["y1"],
        "to_x": bounds["x2"], "to_y": bounds["y2"],
    }
    before = _tiles(client, sid, bounds)
    money_before = _money(client, sid)
    estimate = _estimate(client, sid, action, parameters)
    assert estimate["status"] == "success", estimate
    cost = estimate["changed_entities"]["estimated_cost"]
    assert cost > 0, estimate
    assert _tiles(client, sid, bounds) == before
    assert _money(client, sid) == money_before
    repeated = _estimate(client, sid, action, parameters)
    assert repeated["status"] == "success", repeated
    assert repeated["changed_entities"]["estimated_cost"] == cost
    assert _tiles(client, sid, bounds) == before
    assert _money(client, sid) == money_before

    built = interpret(client, sid, [{
        "action_type": action, "parameters": parameters,
    }], 0)[0]
    assert built["status"] == "success", built
    assert built["changed_entities"]["status"] == "complete", built
    assert built["changed_entities"]["failed"] == []
    spent = money_before - _money(client, sid)
    if action == "connect_rail":
        assert spent == cost
    else:
        # Dry-run road segments can charge clearance again on shared endpoints.
        # The quote is conservative; the live build clears each tile only once.
        assert 0 < spent <= cost
    assert _tiles(client, sid, bounds) != before


def test_partial_build_estimate_reports_failure_without_claiming_construction(
    estimate_world: tuple[httpx.Client, str],
) -> None:
    client, sid = estimate_world
    bounds = _clear_corridor(client, sid)
    before = _tiles(client, sid, bounds)
    money_before = _money(client, sid)
    estimate = _estimate(client, sid, "connect_rail", {
        "from_x": bounds["x1"], "from_y": bounds["y1"],
        "to_x": bounds["x2"], "to_y": bounds["y2"],
        # The first rail piece needs an adjacent entry tile.
        "from_hint_x": bounds["x1"] - 2, "from_hint_y": bounds["y1"],
    })
    assert estimate["status"] == "failed", estimate
    assert estimate["error_name"] == "SEGMENTS_FAILED", estimate
    assert estimate["error"], estimate
    details = estimate["changed_entities"]
    assert details["estimate_only"] is True, estimate
    assert not {"built", "status", "estimated_cost"}.intersection(details), estimate
    assert _tiles(client, sid, bounds) == before
    assert _money(client, sid) == money_before


@pytest.fixture(scope="module")
def blocked_airport(estimate_world: tuple[httpx.Client, str]) -> tuple[httpx.Client, str]:
    """An airport interior cannot serve as a road or rail endpoint."""
    client, sid = estimate_world
    result = interpret(client, sid, [{
        "action_type": "build_airport",
        "parameters": {"x": 181, "y": 203, "airport_type": 1},
    }], 0)[0]
    assert result["status"] == "success", result
    return client, sid


@pytest.mark.parametrize("action", ["connect_rail", "connect_road"])
def test_connection_estimate_preserves_a_real_build_refusal(
    blocked_airport: tuple[httpx.Client, str], action: str,
) -> None:
    client, sid = blocked_airport
    bounds = {"x1": 181, "y1": 203, "x2": 190, "y2": 208}
    before = _tiles(client, sid, bounds)
    money_before = _money(client, sid)
    estimate = _estimate(client, sid, action, {
        "from_x": 183, "from_y": 205, "to_x": 190, "to_y": 205,
        "max_iterations": 2000,
    })
    assert estimate["status"] == "failed", estimate
    assert estimate["error"], estimate
    assert "estimated_cost" not in estimate.get("changed_entities", {})
    assert _tiles(client, sid, bounds) == before
    assert _money(client, sid) == money_before
