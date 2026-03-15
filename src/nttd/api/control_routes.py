import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nttd.api.dependencies import admin_client, agent_registry, orchestrator, world
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


class HeartbeatActionRequest(BaseModel):
    agent_id: str | None = None
    action: str
    params: dict[str, Any] = {}


@router.post("/heartbeat/action")
async def submit_heartbeat_action(request: HeartbeatActionRequest) -> dict[str, bool]:
    """Submit an action to be executed in the current heartbeat window.

    Agents call this during the action window between snapshot delivery and unpause.
    If agent_id is provided, company_id in params is checked against the agent's scope.
    """
    if request.agent_id is not None:
        status = agent_registry.get(request.agent_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Agent {request.agent_id} not found")
        if status.company_scope:
            company_id = request.params.get("company_id")
            if company_id is not None and company_id not in status.company_scope:
                raise HTTPException(
                    status_code=403,
                    detail=f"Agent {request.agent_id} not authorized for company {company_id}",
                )
    orchestrator.submit_heartbeat_action({"action": request.action, "params": request.params})
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


@router.post("/scenario")
async def load_scenario(config_path: str | None = None) -> dict[str, Any]:
    """Load scenario from a HOCON config file and apply settings to the orchestrator.

    config_path: path to a .conf file (default: config/scenario.conf in project root).
    Returns the loaded scenario name and active end conditions.
    """
    from nttd.config import scenario_config  # noqa: PLC0415

    config = scenario_config.load(config_path)
    orchestrator.load_scenario(config)

    ec = config.end_conditions
    return {
        "scenario": config.name,
        "description": config.description,
        "heartbeat_interval_days": config.heartbeat.interval_days,
        "action_window_seconds": config.heartbeat.action_window_seconds,
        "game_speed": config.heartbeat.game_speed,
        "end_conditions": {
            "logic": ec.logic,
            "time_limit": {"enabled": ec.time_limit.enabled, "wall_minutes": ec.time_limit.wall_minutes},
            "game_date_limit": {"enabled": ec.game_date_limit.enabled, "end_year": ec.game_date_limit.end_year},
            "revenue_threshold": {
                "enabled": ec.revenue_threshold.enabled,
                "total_revenue": ec.revenue_threshold.total_revenue,
            },
            "cargo_threshold": {
                "enabled": ec.cargo_threshold.enabled,
                "total_cargo_delivered": ec.cargo_threshold.total_cargo_delivered,
            },
            "max_heartbeats": {"enabled": ec.max_heartbeats.enabled, "count": ec.max_heartbeats.count},
        },
    }
