from typing import Any

from fastapi import APIRouter, HTTPException

from nttd.api.dependencies import action_tracker, admin_client
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/submit", response_model=ActionResult)
def submit_action(envelope: ActionEnvelope) -> ActionResult:
    return action_tracker.submit(envelope)


@router.post("/validate", response_model=ActionResult)
def validate_action(envelope: ActionEnvelope) -> ActionResult:
    # TODO: real validation against current game state
    return ActionResult(action_id=envelope.action_id, status="validated")


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
    """Execute a GameScript command (build, buy, order, etc.). Requires nttd-gs loaded."""
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    return await admin_client.send_gamescript(action, params)
