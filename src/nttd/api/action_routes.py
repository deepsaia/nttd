import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from nttd.api.dependencies import action_tracker, admin_client
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult, ActionStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/actions", tags=["actions"])

# Maps action_type → GS action name.
# action_type uses snake_case names that match GS commands directly,
# so the mapping is 1:1 for most cases. The company_id from the envelope
# is merged into params automatically.
_KNOWN_ACTIONS: set[str] = {
    # Building — road
    "build_road", "build_road_line", "build_road_depot", "build_road_stop",
    "remove_road", "remove_road_depot", "remove_road_stop",
    # Building — rail
    "build_rail", "build_rail_track", "build_rail_station", "build_rail_depot",
    "build_rail_signal", "build_rail_waypoint",
    "remove_rail", "remove_rail_track", "remove_signal", "remove_rail_station",
    "convert_rail",
    # Building — marine
    "build_canal", "build_lock", "build_buoy", "build_water_depot",
    "remove_canal", "remove_lock", "remove_buoy", "remove_water_depot",
    # Building — other
    "build_airport", "remove_airport", "open_close_airport",
    "build_dock", "build_bridge", "build_tunnel", "demolish_tile",
    # Company
    "build_company_hq", "set_loan", "rename_company",
    # Town (GS-exclusive)
    "found_town", "expand_town", "set_town_growth", "perform_town_action",
    "change_town_rating", "set_cargo_goal",
    # Signs
    "build_sign", "remove_sign",
    # Groups
    "create_group", "delete_group", "move_to_group", "set_auto_replace",
    # Vehicles
    "buy_vehicle", "sell_vehicle", "sell_wagon", "move_wagon",
    "start_vehicle", "stop_vehicle", "send_to_depot", "send_to_depot_service",
    "clone_vehicle", "refit_vehicle", "reverse_vehicle", "rename_vehicle",
    # Orders
    "add_order", "insert_order", "remove_order", "skip_to_order",
    "move_order", "set_order_flags", "share_orders", "copy_orders",
    # Subsidies
    "create_subsidy",
}


@router.post("/submit", response_model=ActionResult)
async def submit_action(envelope: ActionEnvelope) -> ActionResult:
    """Submit an action. If action_type maps to a GS command, execute it immediately."""
    action_tracker.submit(envelope)

    if envelope.action_type not in _KNOWN_ACTIONS:
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.REJECTED,
            error=f"Unknown action_type: {envelope.action_type}",
        )

    if not admin_client.connected:
        action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, "Not connected to OpenTTD")
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.FAILED,
            error="Not connected to OpenTTD",
        )

    # Merge company_id into params
    params = dict(envelope.parameters)
    params.setdefault("company_id", envelope.company_id)

    action_tracker.update_result(envelope.action_id, ActionStatus.EXECUTING)
    try:
        gs_result = await admin_client.send_gamescript(envelope.action_type, params)
        if gs_result.get("success"):
            action_tracker.update_result(
                envelope.action_id, ActionStatus.SUCCESS,
                changed_entities=gs_result.get("result", {}),
            )
            return ActionResult(
                action_id=envelope.action_id,
                status=ActionStatus.SUCCESS,
                changed_entities=gs_result.get("result") or {},
            )
        else:
            error = gs_result.get("error", "GS returned failure")
            action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, error)
            return ActionResult(
                action_id=envelope.action_id,
                status=ActionStatus.FAILED,
                error=error,
            )
    except Exception as exc:
        logger.exception("Action execution failed: %s", envelope.action_type)
        action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, str(exc))
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.FAILED,
            error=str(exc),
        )


@router.post("/validate", response_model=ActionResult)
async def validate_action(envelope: ActionEnvelope) -> ActionResult:
    """Validate an action without executing it."""
    if envelope.action_type not in _KNOWN_ACTIONS:
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.REJECTED,
            error=f"Unknown action_type: {envelope.action_type}",
        )
    return ActionResult(action_id=envelope.action_id, status=ActionStatus.VALIDATED)


@router.get("/{action_id}/status", response_model=ActionResult)
def get_action_status(action_id: str) -> ActionResult:
    result = action_tracker.get_result(action_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return result


@router.get("/recent", response_model=list[ActionResult])
def get_recent_actions(limit: int = 50) -> list[ActionResult]:
    return action_tracker.get_recent(limit)


@router.post("/gs/execute")
async def gs_execute(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a raw GS command directly (bypasses action tracking)."""
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await admin_client.send_gamescript(action, params)
