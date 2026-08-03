"""Session-scoped action routes: submit, validate, track actions."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

import nttd.api.dependencies as deps
from nttd.api.participant_auth import (
    AuthorizationHeader,
    ParticipantToken,
    apply_company_scope,
    extract_token,
    resolve_company_id,
)
from nttd.api.scored_guard import require_unscored
from nttd.constants import ACTION_CATEGORIES, KNOWN_ACTIONS, OPERATOR_ACTIONS
from nttd.interpreter.parser import parse_action_list
from nttd.interpreter.validator import validate_actions as validate_agent_actions
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult, ActionStatus

logger = logging.getLogger(__name__)
_ACTIONS_PREFIX = "/sessions/{session_id}/actions"

# gs/execute is operator-tier: it bypasses the KNOWN_ACTIONS allowlist and the
# action log, so it can reach deity powers a human player has no access to and
# leaves no auditable trace. Everything else here is gameplay.
participant_router = APIRouter(prefix=_ACTIONS_PREFIX, tags=["actions"])
operator_router = APIRouter(prefix=_ACTIONS_PREFIX, tags=["actions"])

# Aggregate view used to serve the legacy unprefixed paths.
router = APIRouter()


@participant_router.post("/submit", response_model=ActionResult)
async def submit_action(
    session_id: str,
    envelope: ActionEnvelope,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> ActionResult:
    """Submit an action. If action_type maps to a GS command, execute it immediately."""
    runtime = deps.get_runtime(session_id)
    runtime.action_tracker.submit(envelope)

    if envelope.action_type in OPERATOR_ACTIONS:
        # Refused with a distinct message rather than "unknown": the action does
        # exist, it just has no human equivalent, so using it would make the run
        # unscoreable. Saying so plainly stops an agent retrying it forever.
        error = (
            f"{envelope.action_type} is operator-tier: it has no human-player "
            f"equivalent, so it is not available for play. See the operator tier "
            f"for scenario authoring."
        )
        runtime.action_tracker.update_result(envelope.action_id, ActionStatus.REJECTED, error)
        result = ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.REJECTED,
            error=error,
        )
        # Recorded: reaching for a superhuman power is exactly what an auditor
        # wants to see, even though it was refused.
        _record(runtime, envelope, dict(envelope.parameters), result)
        return result

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

    # The company is decided by the presented token, not by what the caller sent.
    # This OVERWRITES params['company_id'] -- it previously used setdefault, so a
    # caller-supplied value won and any client could act as any company.
    params = dict(envelope.parameters)
    token = extract_token(x_participant_token, authorization)
    company_id = apply_company_scope(runtime, params, token, envelope.company_id)

    # The scenario's action budget applies here, not only to gameloop agents. Every
    # bundled example posts to this route, so enforcing it only at registration
    # bound almost nobody.
    decision = runtime.action_budget.check(company_id)
    if not decision.allowed:
        error = f"Action budget exceeded: {decision.reason}"
        runtime.action_tracker.update_result(envelope.action_id, ActionStatus.BLOCKED, error)
        result = ActionResult(
            action_id=envelope.action_id, status=ActionStatus.BLOCKED, error=error,
        )
        _record(runtime, envelope, params, result)
        return result
    runtime.action_budget.consume(company_id)

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
            result = ActionResult(
                action_id=envelope.action_id,
                status=ActionStatus.SUCCESS,
                changed_entities=gs_result.get("result") or {},
            )
        else:
            error = gs_result.get("error", "GS returned failure")
            runtime.action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, error)
            result = ActionResult(
                action_id=envelope.action_id,
                status=ActionStatus.FAILED,
                error=error,
            )
    except Exception as exc:
        logger.exception("Action execution failed: %s", envelope.action_type)
        runtime.action_tracker.update_result(envelope.action_id, ActionStatus.FAILED, str(exc))
        result = ActionResult(
            action_id=envelope.action_id,
            status=ActionStatus.FAILED,
            error=str(exc),
        )

    # Persist to actions.parquet. Only the gameloop path used to do this, so an
    # action submitted over REST left no audit trail at all -- and a benchmark
    # cannot be verified from an action log that is missing the actions.
    _record(runtime, envelope, params, result)
    return result


def _record(
    runtime: Any, envelope: ActionEnvelope, params: dict[str, Any], result: ActionResult,
) -> None:
    """Write an executed action to the session's action log."""
    recorder = getattr(runtime, "recorder", None)
    if recorder is None:
        return
    try:
        recorder.record_action(
            envelope=ActionEnvelope(
                action_id=envelope.action_id,
                action_type=envelope.action_type,
                parameters=params,
                company_id=params.get("company_id", envelope.company_id),
                mode=envelope.mode,
                metadata={
                    **envelope.metadata,
                    "participant_type": "agent",
                    "game_date": runtime.world.game.game_date,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                },
            ),
            result=result,
        )
    except Exception:
        # The audit trail must not be able to fail the action it describes.
        logger.exception("Could not record action %s", envelope.action_id)


@participant_router.post("/submit-batch")
async def submit_action_batch(
    session_id: str,
    envelopes: list[ActionEnvelope],
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> list[ActionResult]:
    """Submit a batch of actions. All are executed sequentially under the company lock.

    Returns a result for each envelope in the same order. A batch larger than the
    scenario's per-window budget is refused whole rather than part-executed, so a
    contestant cannot use batching to sidestep the ceiling one action at a time.
    """
    runtime = deps.get_runtime(session_id)
    token = extract_token(x_participant_token, authorization)
    if envelopes:
        company_id = resolve_company_id(runtime, token, envelopes[0].company_id)
        decision = runtime.action_budget.check(company_id, count=len(envelopes))
        if not decision.allowed:
            error = f"Action budget exceeded: {decision.reason}"
            results = []
            for envelope in envelopes:
                result = ActionResult(
                    action_id=envelope.action_id, status=ActionStatus.BLOCKED, error=error,
                )
                # Recorded like any other refusal: an auditor reading the action log
                # should see the whole attempt, not only the count in the result row.
                _record(runtime, envelope, dict(envelope.parameters), result)
                results.append(result)
            return results

    results: list[ActionResult] = []
    for envelope in envelopes:
        # Forward the credential so every envelope is scoped, not just the first.
        result = await submit_action(
            session_id, envelope, x_participant_token, authorization,
        )
        results.append(result)
    return results


@participant_router.post("/validate", response_model=ActionResult)
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


@participant_router.get("/{action_id}/status", response_model=ActionResult)
def get_action_status(session_id: str, action_id: str) -> ActionResult:
    runtime = deps.get_runtime(session_id)
    result = runtime.action_tracker.get_result(action_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Action {action_id} not found")
    return result


@participant_router.get("/recent", response_model=list[ActionResult])
def get_recent_actions(session_id: str, limit: int = 50) -> list[ActionResult]:
    runtime = deps.get_runtime(session_id)
    return runtime.action_tracker.get_recent(limit)


@operator_router.post("/gs/execute")
async def gs_execute(session_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a raw GS command directly (bypasses action tracking).

    OPERATOR TIER. This reaches all GameScript commands, including deity powers a
    human player has no access to, and it is not recorded in the action log. It
    exists for scenario authoring and debugging, not for play, so a scored session
    refuses it.
    """
    runtime = deps.get_runtime(session_id)
    # Keyed on whether the session is scored, not on whether tokens were issued.
    # Tokens are addressing -- which company an action is for -- and conflating
    # them with the boundary would refuse this during an unscored multi-agent run
    # while permitting it in a scored single-agent one.
    require_unscored(runtime, "gs/execute", detail=f"action={action}")
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await runtime.admin_client.send_gamescript(action, params)


# ── Interpreter endpoints ──────────────────────────────────────────────
# These mirror the MCP validation/listing tools as REST endpoints,
# plus an interpret endpoint that parses + validates + executes.


@participant_router.get("/available")
def list_available_actions_endpoint() -> dict[str, list[str]]:
    """List all available action types grouped by category."""
    return ACTION_CATEGORIES


@participant_router.post("/interpret/validate")
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


@participant_router.post("/interpret")
async def interpret_agent_actions(
    session_id: str,
    actions: list[dict[str, Any]],
    company_id: int = 0,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
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
        # submit_action re-derives the company from the token, so the
        # company_id query param is only a hint for untokenised sessions.
        result = await submit_action(
            session_id, envelope, x_participant_token, authorization,
        )
        results.append(result)

    return results


# Legacy unprefixed paths. New callers should use the /v1/<tier> prefixes.
router.include_router(participant_router)
router.include_router(operator_router)
