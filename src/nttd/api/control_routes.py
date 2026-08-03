"""Session-scoped control routes: pause, speed, mode, rcon, save/load, assist."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import nttd.api.dependencies as deps
from nttd.api.participant_auth import (
    AuthorizationHeader,
    ParticipantToken,
    apply_company_scope,
    extract_token,
)
from nttd.schemas.game import GameState, RuntimeMode

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions/{session_id}", tags=["control"])


@router.get("/status", response_model=GameState)
def get_status(session_id: str) -> GameState:
    runtime = deps.get_runtime(session_id)
    return runtime.world.game


@router.post("/pause")
async def pause(session_id: str) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    if runtime.admin_client.connected:
        await runtime.admin_client.send_rcon("pause")
    runtime.world.set_paused(True)
    return {"paused": True}


@router.post("/unpause")
async def unpause(session_id: str) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    if runtime.admin_client.connected:
        await runtime.admin_client.send_rcon("unpause")
    runtime.world.set_paused(False)
    return {"paused": False}


@router.post("/speed")
async def set_speed(session_id: str, speed: int) -> dict[str, int]:
    """Rejected: OpenTTD has no runtime game-speed control.

    This endpoint previously issued ``setting game_speed <n>``, which does not
    exist in OpenTTD 15.3 -- the rcon call failed while the endpoint still
    returned ``{"speed": n}``, so callers believed they had changed the pace.

    OpenTTD keeps two clocks. The ECONOMY clock (cargo, payments, finances, and
    everything GSDate reports) is fixed at 1 wall-minute per economy month and
    cannot be changed at all. The CALENDAR clock, which governs vehicle and house
    introduction dates, is set by ``economy.minutes_per_calendar_year`` -- but
    only in wallclock timekeeping and only at map generation, so it belongs in
    the scenario config, not here.
    """
    # Unconditional: the operation does not exist in OpenTTD at all, so session
    # state is irrelevant and resolving it first would only obscure the reason.
    _ = session_id, speed
    raise HTTPException(
        status_code=501,
        detail=(
            "OpenTTD 15.3 has no runtime game-speed setting. The economy clock is "
            "fixed at 1 wall-minute per economy month. To change the calendar pace "
            "(vehicle/house introduction dates), set runtime.timekeeping_units = "
            "'wallclock' and runtime.minutes_per_calendar_year in the scenario "
            "config -- both apply at map generation only."
        ),
    )


@router.post("/mode")
async def set_mode(session_id: str, mode: RuntimeMode) -> dict[str, str]:
    runtime = deps.get_runtime(session_id)

    # Stop existing orchestrator if running
    runtime.orchestrator.stop()
    if runtime.orchestrator_task and not runtime.orchestrator_task.done():
        runtime.orchestrator_task.cancel()
        try:
            await runtime.orchestrator_task
        except asyncio.CancelledError:
            pass

    runtime.world.set_mode(mode)
    runtime.start_orchestrator(mode=mode.value)

    return {"mode": mode.value}


@router.post("/stop")
async def stop_orchestrator(session_id: str) -> dict[str, str]:
    runtime = deps.get_runtime(session_id)
    runtime.orchestrator.stop()
    if runtime.orchestrator_task and not runtime.orchestrator_task.done():
        runtime.orchestrator_task.cancel()
        try:
            await runtime.orchestrator_task
        except asyncio.CancelledError:
            pass
        runtime.orchestrator_task = None
    return {"status": "stopped"}


@router.post("/heartbeat/interval")
def set_heartbeat_interval(session_id: str, days: int) -> dict[str, int]:
    runtime = deps.get_runtime(session_id)
    runtime.orchestrator.set_heartbeat_interval(days)
    return {"heartbeat_interval_days": days}


class HeartbeatActionRequest(BaseModel):
    agent_id: str | None = None
    action: str
    params: dict[str, Any] = {}


@router.post("/heartbeat/action")
async def submit_heartbeat_action(
    session_id: str,
    request: HeartbeatActionRequest,
    x_participant_token: ParticipantToken = None,
    authorization: AuthorizationHeader = None,
) -> dict[str, bool]:
    """Submit an action to be executed in the current heartbeat window."""
    runtime = deps.get_runtime(session_id)

    # The company comes from the token. The agent_registry check below predates
    # tokens and was opt-in -- it only ran when the caller volunteered an
    # agent_id, so omitting it bypassed the check entirely.
    params = dict(request.params)
    token = extract_token(x_participant_token, authorization)
    apply_company_scope(runtime, params, token)

    if request.agent_id is not None:
        status = runtime.agent_registry.get(request.agent_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Agent {request.agent_id} not found")
        if status.company_scope and params["company_id"] not in status.company_scope:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Agent {request.agent_id} not authorized for company "
                    f"{params['company_id']}"
                ),
            )

    runtime.orchestrator.submit_heartbeat_action({"action": request.action, "params": params})
    return {"queued": True}


@router.post("/heartbeat/action_window")
def set_action_window(session_id: str, seconds: float) -> dict[str, float]:
    runtime = deps.get_runtime(session_id)
    runtime.orchestrator.set_action_window(seconds)
    return {"action_window_seconds": seconds}


@router.post("/rcon")
async def send_rcon(session_id: str, command: str) -> dict[str, list[str]]:
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        return {"response": ["Not connected to OpenTTD"]}
    response = await runtime.admin_client.send_rcon(command)
    return {"response": response}


@router.post("/save")
async def save_game(session_id: str, filename: str = "nttd_save") -> dict[str, Any]:
    """Save the current game to a file."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await runtime.admin_client.send_rcon(f"save {filename}")
    return {"filename": filename, "response": response}


@router.post("/load")
async def load_game(session_id: str, filename: str) -> dict[str, Any]:
    """Load a saved game by filename. This will reset the world state."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    response = await runtime.admin_client.send_rcon(f"load {filename}")
    return {"filename": filename, "response": response}


@router.post("/assist")
async def trigger_assist(session_id: str) -> dict[str, Any]:
    """Pause the game and capture a fresh snapshot for human/agent review."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")
    snapshot = await runtime.orchestrator.trigger_assist()
    return snapshot.model_dump()


@router.post("/assist/approve")
async def approve_assist(session_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute the approved action list and unpause the game."""
    runtime = deps.get_runtime(session_id)
    results = await runtime.orchestrator.approve_assist(actions)
    return {"executed": len(results), "results": results}


@router.post("/assist/cancel")
async def cancel_assist(session_id: str) -> dict[str, str]:
    """Cancel the assist session and unpause without executing anything."""
    runtime = deps.get_runtime(session_id)
    await runtime.orchestrator.cancel_assist()
    return {"status": "cancelled"}


@router.post("/scenario")
async def load_scenario(session_id: str, config_path: str | None = None) -> dict[str, Any]:
    """Load scenario from a HOCON config file and apply settings to the orchestrator."""
    from nttd.config import scenario_config  # noqa: PLC0415

    runtime = deps.get_runtime(session_id)
    config = scenario_config.load(config_path)
    runtime.orchestrator.load_scenario(config)

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
