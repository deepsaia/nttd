"""Session-scoped action routes: submit, validate, track actions."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import nttd.api.dependencies as deps
from nttd.constants import ACTION_CATEGORIES, KNOWN_ACTIONS
from nttd.interpreter.parser import parse_action_list
from nttd.interpreter.validator import validate_actions as validate_agent_actions
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult, ActionStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions/{session_id}/actions", tags=["actions"])


@router.post("/submit", response_model=ActionResult)
async def submit_action(session_id: str, envelope: ActionEnvelope) -> ActionResult:
    """Submit an action. If action_type maps to a GS command, execute it immediately."""
    runtime = deps.get_runtime(session_id)
    runtime.action_tracker.submit(envelope)

    if envelope.action_type not in KNOWN_ACTIONS:
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.REJECTED,
            error=f"Unknown action_type: {envelope.action_type}",
        )

    if not runtime.admin_client.connected:
        runtime.action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, "Not connected to OpenTTD")
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.FAILED,
            error="Not connected to OpenTTD",
        )

    # Merge company_id into params
    params = dict(envelope.parameters)
    params.setdefault("company_id", envelope.company_id)

    # The scored clock starts on the first contestant action, so provisioning
    # time is not charged against the wall-clock budget. Idempotent.
    runtime.orchestrator.start_scored_clock()

    runtime.action_tracker.update_result(envelope.action_id, ActionStatus.EXECUTING)
    try:
        # Pathfinding commands (connect_road, connect_rail) run A* in the GS
        # and need more time than single-tile actions.
        timeout = 120.0 if envelope.action_type.startswith("connect_") else 10.0
        gs_result = await runtime.admin_client.send_gamescript(envelope.action_type, params, timeout=timeout)
        if gs_result.get("success"):
            runtime.action_tracker.update_result(
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
            runtime.action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, error)
            return ActionResult(
                action_id=envelope.action_id,
                status=ActionStatus.FAILED,
                error=error,
            )
    except Exception as exc:
        logger.exception("Action execution failed: %s", envelope.action_type)
        runtime.action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, str(exc))
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.FAILED,
            error=str(exc),
        )


@router.post("/submit-batch")
async def submit_action_batch(session_id: str, envelopes: list[ActionEnvelope]) -> list[ActionResult]:
    """Submit a batch of actions. All are executed sequentially under the company lock.

    Returns a result for each envelope in the same order.
    """
    results: list[ActionResult] = []
    for envelope in envelopes:
        result = await submit_action(session_id, envelope)
        results.append(result)
    return results


@router.post("/validate", response_model=ActionResult)
async def validate_action(session_id: str, envelope: ActionEnvelope) -> ActionResult:
    """Validate an action without executing it."""
    deps.get_runtime(session_id)  # verify session is running
    if envelope.action_type not in KNOWN_ACTIONS:
        return ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.REJECTED,
            error=f"Unknown action_type: {envelope.action_type}",
        )
    return ActionResult(action_id=envelope.action_id, status=ActionStatus.VALIDATED)


@router.get("/{action_id}/status", response_model=ActionResult)
def get_action_status(session_id: str, action_id: str) -> ActionResult:
    runtime = deps.get_runtime(session_id)
    result = runtime.action_tracker.get_result(action_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return result


@router.get("/recent", response_model=list[ActionResult])
def get_recent_actions(session_id: str, limit: int = 50) -> list[ActionResult]:
    runtime = deps.get_runtime(session_id)
    return runtime.action_tracker.get_recent(limit)


@router.post("/gs/execute")
async def gs_execute(session_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a raw GS command directly (bypasses action tracking)."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await runtime.admin_client.send_gamescript(action, params)


# ── Interpreter endpoints ──────────────────────────────────────────────
# These mirror the MCP validation/listing tools as REST endpoints,
# plus an interpret endpoint that parses + validates + executes.


@router.get("/available")
def list_available_actions_endpoint() -> dict[str, list[str]]:
    """List all available action types grouped by category."""
    return ACTION_CATEGORIES


@router.post("/interpret/validate")
async def validate_agent_action_list(
    session_id: str, actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a list of agent-produced actions without executing.

    Accepts the same format agents output:
    [{"action_type": "build_road_stop", "parameters": {"tile": 123}}, ...]
    """
    deps.get_runtime(session_id)  # verify session exists
    parsed = parse_action_list(actions)
    errors = validate_agent_actions(parsed)
    results: list[dict[str, Any]] = []
    for i, action in enumerate(parsed):
        if i in errors:
            results.append({"index": i, "status": "invalid", "action_type": action.action_type, "error": errors[i]})
        else:
            results.append({"index": i, "status": "valid", "action_type": action.action_type})
    return {
        "total": len(parsed),
        "valid": len(parsed) - len(errors),
        "invalid": len(errors),
        "results": results,
    }


@router.post("/interpret")
async def interpret_agent_actions(
    session_id: str, actions: list[dict[str, Any]], company_id: int = 0,
) -> list[ActionResult]:
    """Parse, validate, and execute a list of agent-produced actions.

    Accepts the same format agents output:
    [{"action_type": "build_road_stop", "parameters": {"tile": 123}}, ...]

    Each valid action is wrapped in an ActionEnvelope and executed.
    Invalid actions are returned with REJECTED status.
    """
    parsed = parse_action_list(actions)
    errors = validate_agent_actions(parsed)

    results: list[ActionResult] = []
    for i, agent_action in enumerate(parsed):
        if i in errors:
            results.append(ActionResult(
                action_id=f"interp_{i}",
                status=ActionStatus.REJECTED,
                error=errors[i],
            ))
            continue

        envelope = ActionEnvelope(
            action_id=f"interp_{i}",
            company_id=company_id,
            action_type=agent_action.action_type,
            parameters=agent_action.parameters,
        )
        result = await submit_action(session_id, envelope)
        results.append(result)

    return results
