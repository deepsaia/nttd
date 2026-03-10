import asyncio

from fastapi import APIRouter

from nttd.api.dependencies import admin_client, orchestrator, world
from nttd.schemas.game import GameState, RuntimeMode

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
def set_speed(speed: int) -> dict[str, int]:
    world.set_speed(speed)
    return {"speed": speed}


@router.post("/mode")
async def set_mode(mode: RuntimeMode) -> dict[str, str]:
    global _orchestrator_task

    # Stop any running orchestrator
    orchestrator.stop()
    if _orchestrator_task is not None:
        _orchestrator_task.cancel()
        try:
            await _orchestrator_task
        except asyncio.CancelledError:
            pass
        _orchestrator_task = None

    world.set_mode(mode)

    # Start the new mode
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


@router.post("/rcon")
async def send_rcon(command: str) -> dict[str, list[str]]:
    if not admin_client.connected:
        return {"response": ["Not connected to OpenTTD"]}
    response = await admin_client.send_rcon(command)
    return {"response": response}
