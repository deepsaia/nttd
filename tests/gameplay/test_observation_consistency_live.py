"""Compare GameScript facts with their participant-facing snapshot projections.

Uses an isolated, unscored world. Operator subsidy creation is test setup only.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import pytest

from tests.gameplay.test_gs_integration import gs_query, interpret
from tests.gameplay.test_station_cargo_acceptance_live import (
    _build_airport,
)
from tests.gameplay.test_station_cargo_acceptance_live import (
    airport_world as _airport_world,
)

pytestmark = pytest.mark.gs_test
airport_world = _airport_world  # Register the shared fixture for this module.


def _snapshot_when(client: httpx.Client, sid: str, predicate: Callable[[dict], bool]) -> dict:
    deadline = time.monotonic() + 15
    while True:
        response = client.get(f"/v1/participant/sessions/{sid}/state/full")
        response.raise_for_status()
        snapshot = response.json()
        if predicate(snapshot):
            return snapshot
        assert time.monotonic() < deadline, "GameScript changes did not reach the snapshot"
        time.sleep(0.25)


def test_town_facts_and_growth_requirements(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    town = next(t for t in gs_query(client, sid, "get_towns") if t["id"] == 19)
    detail = gs_query(client, sid, "get_town_info", {"town_id": 19})
    snapshot = _snapshot_when(client, sid, lambda s: bool(s["towns"]))
    projected = next(t for t in snapshot["towns"] if t["id"] == 19)
    for view in (town, detail, projected):
        assert view["is_city"] is True, view
        assert view["houses"] > 0, view
        assert view["growth_rate"] > 0, view
    assert "accepts_cargo" not in detail
    assert isinstance(detail["growth_requirements"], list)
    assert all(r["goal_per_month"] > 0 and r["cargo_types"] for r in detail["growth_requirements"])
    # TE_GOODS is 3, while GOOD cargo is 5 on this map. This exercises the
    # distinction that an empty default requirement list cannot verify.
    response = client.post(
        f"/v1/operator/sessions/{sid}/actions/gs/execute", params={"action": "set_cargo_goal"},
        json={"town_id": 19, "town_effect": 3, "goal": 123},
    )
    response.raise_for_status()
    assert response.json()["success"], response.json()
    detail = gs_query(client, sid, "get_town_info", {"town_id": 19})
    goal = next(r for r in detail["growth_requirements"] if r["town_effect_id"] == 3)
    assert goal["goal_per_month"] == 123
    assert {c["cargo_label"] for c in goal["cargo_types"]} == {"GOOD"}


def test_unserved_factory_output_survives_projection(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    raw = next(i for i in gs_query(client, sid, "get_industries") if i["id"] == 36)
    snapshot = _snapshot_when(client, sid, lambda s: bool(s["industries"]))
    projected = next(i for i in snapshot["industries"] if i["id"] == 36)
    for view in (raw, projected):
        assert view["production"] == []
        assert any(c["cargo_label"] == "GOOD" for c in view["produces_cargo"])
        assert view["nearby_stations"] == []
        assert "served_by" not in view
    assert projected["accepts_cargo"] == raw["accepts_cargo"]


def test_removed_airport_disappears_from_snapshot(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    station_id = _build_airport(client, sid, 181, 203)
    _snapshot_when(client, sid, lambda s: any(v["id"] == station_id for v in s["stations"]))
    removed = interpret(client, sid, [{
        "action_type": "remove_airport", "parameters": {"x": 181, "y": 203},
    }], 0)[0]
    assert removed["status"] == "success", removed
    assert all(s["id"] != station_id for s in gs_query(client, sid, "get_stations"))
    _snapshot_when(client, sid, lambda s: all(v["id"] != station_id for v in s["stations"]))


def test_vehicle_order_indices_and_stopped_state_agree(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    stations = [_build_airport(client, sid, x, y) for x, y in ((120, 50), (181, 203))]
    hangar = next(h for h in gs_query(client, sid, "get_hangars") if h["station_id"] == stations[0])
    purchase = interpret(client, sid, [{
        "action_type": "buy_vehicle",
        "parameters": {"depot_tile": hangar["hangar_tile"], "engine_id": 217},
    }], 0)[0]
    assert purchase["status"] == "success", purchase
    vehicle_id = purchase["changed_entities"]["vehicle_id"]
    orders = interpret(client, sid, [{
        "action_type": "add_order", "parameters": {"vehicle_id": vehicle_id, "station_id": station},
    } for station in stations], 0)
    assert all(r["status"] == "success" for r in orders), orders
    fleet = next(v for v in gs_query(client, sid, "get_vehicles") if v["id"] == vehicle_id)
    detail = gs_query(client, sid, "get_vehicle_info", {"vehicle_id": vehicle_id})
    snapshot = _snapshot_when(client, sid, lambda s: any(
        v["id"] == vehicle_id and len(v["orders"]) == 2 for v in s["vehicles"]
    ))
    projected = next(v for v in snapshot["vehicles"] if v["id"] == vehicle_id)
    for view in (fleet, detail, projected):
        assert [order["index"] for order in view["orders"]] == [0, 1], view
        assert view["running"] is False, view


def test_subsidy_endpoints_and_expiry_survive_projection(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    industries = gs_query(client, sid, "get_industries")
    source = next(i for i in industries if any(c["cargo_label"] == "COAL" for c in i["produces_cargo"]))
    target = next(i for i in industries if any(c["cargo_label"] == "COAL" for c in i["accepts_cargo"]))
    cargo = next(c for c in source["produces_cargo"] if c["cargo_label"] == "COAL")
    date_before = gs_query(client, sid, "get_date")["date"]
    response = client.post(
        f"/v1/operator/sessions/{sid}/actions/gs/execute", params={"action": "create_subsidy"},
        json={"cargo_type": cargo["cargo_id"], "from_type": 0, "from_id": source["id"],
              "to_type": 0, "to_id": target["id"]},
    )
    response.raise_for_status()
    assert response.json()["success"], response.json()
    raw = next(s for s in gs_query(client, sid, "get_subsidies") if
               s["source_index"] == source["id"] and s["destination_index"] == target["id"])
    snapshot = _snapshot_when(client, sid, lambda s: any(v["id"] == raw["id"] for v in s["subsidies"]))
    projected = next(s for s in snapshot["subsidies"] if s["id"] == raw["id"])
    assert projected["cargo_id"] == cargo["cargo_id"]
    assert projected["cargo_label"] == "COAL"
    assert projected["src_type"] == projected["dst_type"] == "industry"
    assert projected["src_id"] == source["id"] and projected["src_name"] == source["name"]
    assert projected["dst_id"] == target["id"] and projected["dst_name"] == target["name"]
    assert projected["is_awarded"] is False
    date_after = gs_query(client, sid, "get_date")["date"]
    # Direct queries and heartbeat snapshots are asynchronous. Compare within
    # the actual elapsed game days, not an assumed wall-time refresh interval.
    assert 0 < projected["remaining_days"] <= 366
    assert abs(projected["remaining_days"] - raw["remaining_days"]) <= date_after - date_before + 1
    assert "remaining_years" not in projected and "value" not in projected


def test_finance_observations_have_authoritative_quarter_history(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    raw = gs_query(client, sid, "get_company_finance", {"company_id": 0})
    snapshot = _snapshot_when(client, sid, lambda s: bool(s["companies"]))
    company = next(c for c in snapshot["companies"] if c["id"] == 0)
    for view in (raw, company):
        assert isinstance(view["finance_date"], int)
        assert isinstance(view["finance_quarter"], int)
        assert len(view["completed_quarter_income"]) > 0
    assert company["episode_revenue"] == 0  # No vehicle in this world has delivered cargo.
    assert company["profit_last_year"] is None


def test_capped_trace_does_not_report_disconnection(airport_world: tuple[httpx.Client, str]) -> None:
    client, sid = airport_world
    params = {"from_x": 10, "from_y": 10, "to_x": 11, "to_y": 11, "transport_type": "rail"}
    capped = gs_query(client, sid, "trace_route", {**params, "max_iterations": 1})
    assert capped["exhausted"] is True and capped["line_exists"] is None, capped
    completed = gs_query(client, sid, "trace_route", {**params, "max_iterations": 10})
    assert completed["exhausted"] is False and completed["line_exists"] is False, completed
