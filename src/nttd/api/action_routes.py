"""Session-scoped action routes: submit, validate, track actions."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

import nttd.api.dependencies as deps
from nttd.actions.gate import admit
from nttd.actions.gs_reply import result_from_reply
from nttd.api.participant_auth import (
    AuthorizationHeader,
    ParticipantToken,
    apply_company_scope,
    extract_token,
    resolve_company_id,
)
from nttd.api.scored_guard import require_unscored
from nttd.constants import ACTION_CATEGORIES, KNOWN_ACTIONS
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


# Statuses an action does not move on from. A resend of one of these is a retry of
# something already decided, not a new request. PENDING and EXECUTING are excluded on
# purpose: a resend while the first attempt is still running is a different problem, and
# answering it from the tracker would report a result that does not exist yet.
_SETTLED = frozenset({
    ActionStatus.SUCCESS,
    ActionStatus.PARTIAL,
    ActionStatus.FAILED,
    ActionStatus.REJECTED,
    ActionStatus.BLOCKED,
})


def _already_settled(runtime: Any, action_id: str) -> ActionResult | None:
    """The stored result for an action that has already run, if there is one.

    ``action_id`` is supplied by the caller, which makes it usable as an idempotency
    key. ``connect_road`` can take two minutes, and a proxy or an impatient client that
    gives up and resends would otherwise build the route a second time and pay for it
    twice.
    """
    existing = runtime.action_tracker.get_result(action_id)
    if existing is not None and existing.status in _SETTLED:
        return existing
    return None


@participant_router.post("/submit", response_model=ActionResult)
async def submit_action(
    session_id: str,
    envelope: ActionEnvelope,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> ActionResult:
    """Submit an action. If action_type maps to a GS command, execute it immediately."""
    runtime = deps.get_runtime(session_id)

    # A retry of an action already carried out returns what happened the first time
    # rather than doing it again. connect_road can run for two minutes, which is long
    # enough for a proxy or an impatient client to give up and resend, and building the
    # route twice would charge twice for track that is already there.
    settled = _already_settled(runtime, envelope.action_id)
    if settled is not None:
        logger.info("Replaying settled action %s rather than running it again", envelope.action_id)
        return settled

    runtime.action_tracker.submit(envelope)

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

    # Operator tier and allowlist, in one check shared with the stepped path. They
    # used to be inline branches here and nothing at all there, so the stepped loop
    # reached operator-tier commands unguarded.
    #
    # No budget: real-time play has no action ceiling. The world moves whether or not
    # a contestant acts, so spending actions already costs game time, and how many a
    # multi-agent system fires is its own business. The ceiling belongs to stepped
    # play, where the world waits and an unbounded batch would be a free lunch.
    admission = admit(envelope.action_type, company_id)
    if not admission.allowed:
        runtime.action_tracker.update_result(
            envelope.action_id, admission.status, admission.error,
        )
        result = ActionResult(
            action_id=envelope.action_id,
            status=admission.status,
            error=admission.error,
        )
        # Recorded whatever the reason: reaching for a superhuman power, or running
        # into the ceiling, is exactly what an auditor wants to see.
        _record(runtime, envelope, params, result)
        return result

    # The scored clock starts on the first contestant action, so provisioning
    # time is not charged against the wall-clock budget. Idempotent.
    runtime.orchestrator.start_scored_clock()

    runtime.action_tracker.update_result(envelope.action_id, ActionStatus.EXECUTING)
    try:
        # Pathfinding commands (connect_road, connect_rail) run A* in the GS
        # and need more time than single-tile actions.
        timeout = 120.0 if envelope.action_type.startswith("connect_") else 10.0
        gs_result = await runtime.admin_client.send_gamescript(envelope.action_type, params, timeout=timeout)
        result = result_from_reply(envelope.action_id, gs_result)
        runtime.action_tracker.update_result(
            envelope.action_id, result.status, result.error,
            changed_entities=result.changed_entities,
        )
        # Same call the stepped flush makes, so the stored map is kept current whichever
        # way an action arrived. Real time has no step boundary to hang this on, which is
        # why it belongs at the action rather than at the step.
        await runtime.orchestrator.refresh_changed_tiles(envelope, result)
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

    Returns a result for each envelope in the same order.

    No ceiling here. Real-time play is unbounded: the world moves whether or not a
    contestant acts, so a large batch already pays for itself in game time, and a
    multi-agent system that wants to submit more is doing work it paid for. The
    ceiling belongs to stepped play, where the world waits for the batch.
    """
    runtime = deps.get_runtime(session_id)
    token = extract_token(x_participant_token, authorization)
    if envelopes:
        resolve_company_id(runtime, token, envelopes[0].company_id)

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
