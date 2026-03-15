import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from nttd.api.dependencies import admin_client, orchestrator, world
from nttd.schemas.game import GameState, RuntimeMode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session", tags=["control"])

_orchestrator_task: asyncio.Task | None = None


@router.get("/status", response_model=GameState)
def get_status() -> GameState:
    return world.game


@router.post("/pause")
async def pause() -> dict[str, bool]:
    if admin_client.connected:
        await admin_client.send_rcon("pause")
    world.set_paused(True)
    return {"paused": True}


@router.post("/unpause")
async def unpause() -> dict[str, bool]:
    if admin_client.connected:
        await admin_client.send_rcon("unpause")
    world.set_paused(False)
    return {"paused": False}


@router.post("/speed")
async def set_speed(speed: int) -> dict[str, int]:
    if admin_client.connected:
        await admin_client.send_rcon(f"setting game_speed {speed}")
    world.set_speed(speed)
    return {"speed": speed}


@router.post("/mode")
async def set_mode(mode: RuntimeMode) -> dict[str, str]:
    global _orchestrator_task

    orchestrator.stop()
    if _orchestrator_task is not None:
        _orchestrator_task.cancel()
        try:
            await _orchestrator_task
        except asyncio.CancelledError:
            pass
        _orchestrator_task = None

    world.set_mode(mode)

    if mode == RuntimeMode.HEARTBEAT:
        _orchestrator_task = asyncio.create_task(orchestrator.run_heartbeat())
    elif mode == RuntimeMode.ASYNC_REALTIME:
        _orchestrator_task = asyncio.create_task(orchestrator.run_async_realtime())

    return {"mode": mode.value}


@router.post("/stop")
async def stop_orchestrator() -> dict[str, str]:
    global _orchestrator_task
    orchestrator.stop()
    if _orchestrator_task is not None:
        _orchestrator_task.cancel()
        try:
            await _orchestrator_task
        except asyncio.CancelledError:
            pass
        _orchestrator_task = None
    return {"status": "stopped"}


@router.post("/heartbeat/interval")
def set_heartbeat_interval(days: int) -> dict[str, int]:
    orchestrator.set_heartbeat_interval(days)
    return {"heartbeat_interval_days": days}


@router.post("/heartbeat/action")
async def submit_heartbeat_action(action: dict[str, Any]) -> dict[str, bool]:
    """Submit an action to be executed in the current heartbeat window.

    Agents call this during the action window between snapshot delivery and unpause.
    Format: { "action": "buy_vehicle", "params": { "company_id": 0, ... } }
    """
    orchestrator.submit_heartbeat_action(action)
    return {"queued": True}


@router.post("/heartbeat/action_window")
def set_action_window(seconds: float) -> dict[str, float]:
    orchestrator.set_action_window(seconds)
    return {"action_window_seconds": seconds}


@router.post("/rcon")
async def send_rcon(command: str) -> dict[str, list[str]]:
    if not admin_client.connected:
        return {"response": ["Not connected to OpenTTD"]}
    response = await admin_client.send_rcon(command)
    return {"response": response}


@router.post("/save")
async def save_game(filename: str = "nttd_save") -> dict[str, Any]:
    """Save the current game to a file. Saved into the OpenTTD save directory."""
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await admin_client.send_rcon(f"save {filename}")
    return {"filename": filename, "response": response}


@router.post("/load")
async def load_game(filename: str) -> dict[str, Any]:
    """Load a saved game by filename. This will reset the world state."""
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await admin_client.send_rcon(f"load {filename}")
    return {"filename": filename, "response": response}


@router.post("/assist")
async def trigger_assist() -> dict[str, Any]:
    """Pause the game and capture a fresh snapshot for human/agent review.

    Returns the current game snapshot. The game stays paused until
    POST /session/assist/approve or /session/assist/cancel is called.
    """
    if not admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    snapshot = await orchestrator.trigger_assist()
    return snapshot.model_dump()


@router.post("/assist/approve")
async def approve_assist(actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute the approved action list and unpause the game.

    Body: list of { "action": "...", "params": { ... } } GS commands.
    Returns the result of each executed action.
    """
    results = await orchestrator.approve_assist(actions)
    return {"executed": len(results), "results": results}


@router.post("/assist/cancel")
async def cancel_assist() -> dict[str, str]:
    """Cancel the assist session and unpause without executing anything."""
    await orchestrator.cancel_assist()
    return {"status": "cancelled"}
