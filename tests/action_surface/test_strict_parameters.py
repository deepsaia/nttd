"""Malformed commands fail before dispatch, regardless of how they reach nttd."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from jsonschema import Draft202012Validator

from nttd.actions.tracker import ActionTracker
from nttd.actions.validation import parameter_schema, validate_parameters
from nttd.api import action_routes, observation_routes
from nttd.config import action_manifest
from nttd.mcp.game_session import GameSession
from nttd.mcp.snapshot import reshape_query
from nttd.runtime.orchestrator import Orchestrator
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.state.world import WorldState


@pytest.mark.parametrize("name", sorted(action_manifest.ACTIONS))
def test_every_lookup_schema_is_valid(name):
    Draft202012Validator.check_schema(parameter_schema(name))


@pytest.mark.parametrize(
    "params", [{"vehicle_id": "6"}, {"vehicle_id": True}, {"vehicle_id": 6.0}, {"vehicle_id": None}]
)
def test_ids_are_integers_without_coercion(params):
    assert "integer" in validate_parameters("start_vehicle", params)


def test_unknown_field_names_are_explained_not_ignored():
    error = validate_parameters("trace_route", {"from_x": 1, "from_y": 2, "to_x": 3, "to_y": 4, "vehicle_type": "road"})
    assert "unknown parameter(s): vehicle_type" in error
    assert "transport_type" in error
    assert "list_commands" in error


def test_required_and_optional_alternatives():
    assert "industry_id or town_id" in validate_parameters("find_station_spot", {})
    assert validate_parameters("find_station_spot", {"town_id": 19}) is None
    assert validate_parameters("clone_vehicle", {"vehicle_id": 6}) is None
    assert validate_parameters("clone_vehicle", {"vehicle_id": 6, "depot_x": 1})
    assert validate_parameters("clone_vehicle", {"vehicle_id": 6, "depot_x": 1, "depot_y": 2}) is None


def test_nested_estimate_inherits_company_and_validates_target_contract():
    assert (
        validate_parameters("estimate_cost", {"action": "build_road_stop", "params": {"x": 1, "y": 2, "direction": 3}})
        is None
    )
    error = validate_parameters("estimate_cost", {"action": "start_vehicle", "params": {"vehicle_id": "6"}})
    assert "parameters.params" in error and "integer" in error
    for action in ["estimate_cost", "change_bank_balance", "get_towns", "not_a_command"]:
        assert "gameplay command" in validate_parameters("estimate_cost", {"action": action, "params": {}})


def test_build_path_checks_nested_steps_and_accepts_pathfinder_metadata():
    steps = [{"x": 1, "y": 2}, {"x": 1, "y": 5, "action": "build_bridge"}]
    assert "bridge_from_x" in validate_parameters("build_path", {"steps": steps})
    steps[1].update(bridge_from_x=1, bridge_from_y=2, length=3)
    assert validate_parameters("build_path", {"steps": steps}) is None
    steps[1]["typo"] = 1
    assert "parameters.steps[1]" in validate_parameters("build_path", {"steps": steps})
    assert "not one of" in validate_parameters("build_path", {"steps": steps, "transport_type": "air"})


def test_area_error_has_inclusive_size_and_configured_limit():
    params = {"x1": 0, "y1": 0, "x2": 20, "y2": 20}
    error = validate_parameters("get_tile_area", params)
    assert "441 tiles" in error and "400" in error and "inclusive" in error
    assert validate_parameters("get_tile_area", {**params, "max_tiles": 441}) is None


def runtime():
    client = MagicMock(connected=True)
    client.send_gamescript = AsyncMock(return_value={"success": True, "result": {"vehicle_id": 6}})
    participants = MagicMock()
    participants.is_empty.return_value = True
    return SimpleNamespace(
        admin_client=client,
        participants=participants,
        action_tracker=ActionTracker(),
        recorder=None,
        orchestrator=SimpleNamespace(start_scored_clock=MagicMock(), refresh_changed_tiles=AsyncMock()),
    )


def test_submit_batch_and_dry_run_share_refusal_and_never_dispatch(monkeypatch):
    rt = runtime()
    monkeypatch.setattr(action_routes.deps, "get_runtime", lambda _: rt)
    envelope = ActionEnvelope(
        action_id="test:1", action_type="start_vehicle", parameters={"vehicle_id": "6"}, company_id=0
    )
    dry = asyncio.run(action_routes.validate_action("test", envelope))
    result = asyncio.run(action_routes.submit_action_batch("test", [envelope]))[0]
    assert result.status == dry.status == "rejected"
    assert result.error == dry.error
    assert result.error_name == "INVALID_PARAMETERS"
    assert result.action_type == "start_vehicle"
    assert rt.action_tracker.get_result(envelope.action_id) == result
    rt.admin_client.send_gamescript.assert_not_called()
    rt.orchestrator.start_scored_clock.assert_not_called()


def test_real_time_receipt_and_replay_keep_identity_and_game_error(monkeypatch):
    rt = runtime()
    rt.admin_client.send_gamescript.return_value = {
        "success": False,
        "error": "Invalid station_id 999",
        "error_name": "INVALID_STATION_ID",
    }
    monkeypatch.setattr(action_routes.deps, "get_runtime", lambda _: rt)
    envelope = ActionEnvelope(
        action_id="test:1", action_type="add_order", parameters={"vehicle_id": 6, "station_id": 999}, company_id=0
    )
    result = asyncio.run(action_routes.submit_action("test", envelope))
    replay = asyncio.run(action_routes.submit_action("test", envelope))
    assert result == replay
    assert result.action_type == "add_order" and result.error_name == "INVALID_STATION_ID"
    assert rt.admin_client.send_gamescript.await_count == 1


def test_queries_are_validated_before_gamescript(monkeypatch):
    rt = runtime()
    monkeypatch.setattr(observation_routes.deps, "get_runtime", lambda _: rt)
    result = asyncio.run(observation_routes.gs_query("test", "find_station_spot", {}))
    assert result["error_name"] == "INVALID_PARAMETERS"
    rt.admin_client.send_gamescript.assert_not_called()


def test_stepped_execution_uses_same_contract():
    rt = runtime()
    orchestrator = Orchestrator(WorldState(), rt.admin_client)
    orchestrator.action_tracker = rt.action_tracker
    outcomes = asyncio.run(
        orchestrator._execute_actions([{"action": "start_vehicle", "params": {"vehicle_id": "6", "company_id": 0}}])
    )
    assert outcomes[0].status == "rejected"
    assert outcomes[0].error_name == "INVALID_PARAMETERS"
    assert rt.action_tracker.get_result(outcomes[0].action_id) == outcomes[0]
    rt.admin_client.send_gamescript.assert_not_called()


def test_lookup_publishes_same_contract_and_corrected_returns():
    session = GameSession(MagicMock())
    assert session.lookup_action("build_path")["parameter_schema"] == parameter_schema("build_path")
    estimate = session.lookup_action("estimate_cost")
    assert estimate["returns"]["fields"] == ["action", "estimated_cost"]
    assert session.lookup_action("get_vehicle_info")["returns"]["nested"]["cargo"] == ["cargo_id", "capacity", "loaded"]


def test_vehicle_queries_use_observation_words_without_losing_details():
    info = {"state": 1, "current_speed": 0, "lost": True, "idle_reason": "stopped", "cargo": []}
    reply = reshape_query("get_vehicle_info", {"success": True, "result": info})
    assert reply["result"] == {**info, "state": "stopped"}
    fleet = reshape_query("get_vehicles", {"success": True, "result": [info]})
    assert fleet["result"][0]["state"] == "stopped"


@pytest.mark.parametrize("command", ["get_engines", "get_vehicles", "create_group"])
def test_vehicle_types_accept_documented_names_and_numeric_codes(command):
    for value in ["train", "road", "ship", "aircraft", 0, 1, 2, 3]:
        assert validate_parameters(command, {"vehicle_type": value}) is None
    assert validate_parameters(command, {"vehicle_type": "bus"})
    assert validate_parameters(command, {"vehicle_type": 99})


def test_closed_enums_reject_unknown_values_but_order_flags_can_be_combined():
    assert validate_parameters("build_airport", {"x": 1, "y": 2, "airport_type": 999})
    assert validate_parameters("add_order", {"vehicle_id": 6, "station_id": 1, "order_flags": 10}) is None


def test_stepped_receipt_keeps_structured_game_errors_in_audit_and_tracker():
    rt = runtime()
    rt.admin_client.send_gamescript.return_value = {
        "success": False,
        "error": "Invalid station_id 999",
        "error_name": "INVALID_STATION_ID",
    }
    recorder = MagicMock()
    orchestrator = Orchestrator(WorldState(), rt.admin_client, recorder=recorder)
    orchestrator.action_tracker = rt.action_tracker
    orchestrator.refresh_changed_tiles = AsyncMock()
    outcomes = asyncio.run(
        orchestrator._execute_actions(
            [
                {
                    "action": "add_order",
                    "params": {"vehicle_id": 6, "station_id": 999, "company_id": 0},
                }
            ]
        )
    )
    result = outcomes[0]
    assert result.action_type == "add_order" and result.error_name == "INVALID_STATION_ID"
    assert recorder.record_action.call_args.kwargs["result"] == result
    assert rt.action_tracker.get_result(result.action_id) == result
