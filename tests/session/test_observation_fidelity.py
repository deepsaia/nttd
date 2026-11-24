"""Keep game facts intact across the direct-query, world and compact views."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nttd.actions.tracker import ActionTracker
from nttd.api import observation_routes
from nttd.schemas.town import Town
from nttd.state.world import WorldState


def test_town_details_are_preserved_and_missing_legacy_details_stay_unknown() -> None:
    world = WorldState()
    world.apply_gs_towns([
        {"id": 19, "name": "Great Mennford", "population": 2152, "houses": 72,
         "is_city": True, "growth_rate": 43, "x": 113, "y": 45},
        {"id": 20, "name": "Legacy town", "population": 1500, "x": 10, "y": 20},
    ])
    current, legacy = world.snapshot().towns
    assert (current.houses, current.is_city, current.growth_rate) == (72, True, 43)
    assert (legacy.houses, legacy.is_city, legacy.growth_rate) == (None, None, None)


def test_industry_capabilities_survive_before_its_first_month_of_production() -> None:
    world = WorldState()
    goods = [{"cargo_id": 5, "cargo_label": "GOOD"}]
    grain = [{"cargo_id": 6, "cargo_label": "GRAI"}]
    nearby = [{"station_id": 8, "name": "Nearby bus stop", "x": 9, "y": 10, "distance": 1}]
    world.apply_gs_industries([{
        "id": 36, "name": "Factory", "x": 10, "y": 10,
        "production": [], "accepted": grain, "produces_cargo": goods,
        "accepts_cargo": grain, "nearby_stations": nearby, "nearby_stations_company_id": 0,
    }])
    observed = world.snapshot().industries[0].model_dump()
    assert observed["production"] == []
    assert observed["produces_cargo"] == goods
    assert observed["accepts_cargo"] == grain
    assert observed["nearby_stations"] == nearby
    assert observed["nearby_stations_company_id"] == 0
    assert "served_by" not in observed


def test_legacy_industry_proximity_is_relabelled_without_inventing_capabilities() -> None:
    world = WorldState()
    nearby = [{"station_id": 8, "name": "Old station", "x": 9, "y": 10, "distance": 1}]
    world.apply_gs_industries([{"id": 36, "served_by": nearby}])
    observed = world.snapshot().industries[0].model_dump()
    assert observed["nearby_stations"] == nearby
    assert observed["nearby_stations_company_id"] is None
    assert observed["produces_cargo"] is None
    assert observed["accepts_cargo"] is None


def test_industry_proximity_scope_survives_global_snapshot_refresh() -> None:
    world = WorldState()
    for company_id in (0, 1):
        world.apply_gs_industries([{
            "id": 36, "nearby_stations": [], "nearby_stations_company_id": company_id,
        }])
        industry = world.snapshot().industries[0]
        assert industry.nearby_stations == []
        assert industry.nearby_stations_company_id == company_id


def test_station_refresh_removes_only_missing_stations_of_that_company() -> None:
    world = WorldState()
    world.apply_gs_stations(0, [{"id": 1}, {"id": 2}])
    world.apply_gs_stations(1, [{"id": 3}])
    world.apply_gs_stations(0, [{"id": 2, "name": "Updated"}])
    assert set(world.stations) == {2, 3}
    assert world.stations[2].name == "Updated"
    world.apply_gs_stations(0, [])
    assert set(world.stations) == {3}


def _subsidy() -> dict:
    # These are the GameScript's names, not the snapshot schema's names.
    return {
        "id": 7, "is_awarded": True, "cargo_type": 1, "cargo_label": "COAL",
        "source_type": 0, "source_index": 38, "source_name": "Coal Mine",
        "destination_type": 1, "destination_index": 19,
        "destination_name": "Great Mennford", "remaining_days": 120,
    }


def test_subsidy_cargo_route_award_and_day_units_are_preserved() -> None:
    world = WorldState()
    world.apply_gs_subsidies([_subsidy()])
    assert world.snapshot().subsidies[0].model_dump() == {
        "id": 7, "cargo_id": 1, "cargo_label": "COAL",
        "src_type": "industry", "src_id": 38, "src_name": "Coal Mine",
        "dst_type": "town", "dst_id": 19, "dst_name": "Great Mennford",
        "is_awarded": True, "remaining_days": 120,
    }


def test_legacy_subsidy_days_and_zero_endpoint_id_are_not_lost() -> None:
    world = WorldState()
    world.towns[0] = Town(id=0, name="Town Zero")
    world.apply_gs_subsidies([{
        "id": 8, "cargo_type": 0, "source_type": 1, "source_index": 0,
        "destination_type": 1, "destination_index": 99, "remaining": 30,
    }])
    subsidy = world.subsidies[0]
    assert subsidy.cargo_id == subsidy.src_id == 0
    assert subsidy.src_name == "Town Zero"
    assert subsidy.dst_name is None
    assert subsidy.remaining_days == 30
    assert subsidy.is_awarded is None
    assert subsidy.cargo_label is None
    world.apply_gs_subsidies([{"id": 9, "remaining_years": 0}])
    assert world.subsidies[0].remaining_days is None


@pytest.mark.asyncio
async def test_compact_subsidies_keep_the_route_and_real_expiry(monkeypatch) -> None:
    world = WorldState()
    world.apply_gs_subsidies([_subsidy(), {"id": 8}])
    runtime = SimpleNamespace(world=world, action_tracker=ActionTracker(), snapshot_broker_registry={})
    monkeypatch.setattr(observation_routes.deps, "get_runtime", lambda _: runtime)
    compact = await observation_routes.get_compact_state("test")
    assert [s.model_dump() for s in compact.subsidies] == [s.model_dump() for s in world.subsidies]
    assert "remaining_years" not in compact.subsidies[0].model_dump()
    assert "value" not in compact.subsidies[0].model_dump()


@pytest.mark.parametrize("state", [1, 2, 3, 4, 5, 255])
def test_nonrunning_states_do_not_turn_into_running_outside_a_depot(state: int) -> None:
    world = WorldState()
    world.apply_gs_vehicles(0, [{"id": 10, "state": state, "in_depot": False}])
    assert world.vehicles[10].running is False


def test_vehicle_running_uses_explicit_game_report_and_unknown_stays_unknown() -> None:
    world = WorldState()
    world.apply_gs_vehicles(0, [
        {"id": 1, "state": 0, "running": False, "in_depot": False},
        {"id": 2, "state": 0}, {"id": 3},
    ])
    assert world.vehicles[1].running is False
    assert world.vehicles[2].running is True
    assert world.vehicles[3].running is None
    assert world.vehicles[3].state is None


def test_fleet_orders_preserve_indices_and_waypoint_and_conditional_kinds() -> None:
    world = WorldState()
    world.apply_gs_vehicles(0, [{"id": 10, "orders": [
        {"index": 0, "destination": 100, "is_goto_station": True},
        {"index": 1, "destination": 200, "is_goto_waypoint": True},
        {"index": 2, "destination": 300, "is_goto_depot": True},
        {"index": 3, "is_conditional": True},
    ]}])
    orders = world.vehicles[10].orders
    assert [o.index for o in orders] == [0, 1, 2, 3]
    assert orders[1].is_goto_waypoint and not orders[1].is_goto_station
    assert orders[3].is_conditional
    # Older fleet replies omitted indices, but their list order was still known.
    world.apply_gs_vehicles(0, [{"id": 10, "orders": [{}, {}]}])
    assert [o.index for o in world.vehicles[10].orders] == [0, 1]
