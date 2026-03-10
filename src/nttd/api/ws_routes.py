import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nttd.api.dependencies import agent_registry, world

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_ws_connections: dict[str, WebSocket] = {}
_push_tasks: dict[str, asyncio.Task] = {}


@router.websocket("/ws/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    status = agent_registry.get(agent_id)
    if status is None:
        await websocket.close(code=4004, reason=f"Agent {agent_id} not connected")
        return

    await websocket.accept()
    _ws_connections[agent_id] = websocket
    logger.info("WebSocket connected: %s", agent_id)

    push_task = asyncio.create_task(_push_loop(agent_id, websocket))
    _push_tasks[agent_id] = push_task

    try:
        while True:
            # Keep connection alive; handle incoming messages (actions, pings)
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", agent_id)
    finally:
        push_task.cancel()
        _push_tasks.pop(agent_id, None)
        _ws_connections.pop(agent_id, None)


async def _push_loop(agent_id: str, websocket: WebSocket) -> None:
    """Push snapshots to connected agent based on their subscription cadence."""
    while True:
        subs = agent_registry.get_subscriptions(agent_id)
        if not subs:
            await asyncio.sleep(2.0)
            continue

        # Use the minimum cadence (in game-days) across all subscriptions
        min_cadence = min(s.cadence for s in subs)
        interval = max(1.0, min_cadence * 0.5)  # rough: 1 game-day ~ 0.5s at normal speed

        await asyncio.sleep(interval)

        snapshot = world.snapshot()
        try:
            await websocket.send_json({
                "type": "snapshot",
                "data": snapshot.model_dump(),
            })
        except Exception:
            break


async def broadcast_snapshot() -> None:
    """Broadcast a snapshot to all connected WebSocket agents."""
    if not _ws_connections:
        return
    snapshot = world.snapshot()
    payload = {"type": "snapshot", "data": snapshot.model_dump()}
    disconnected = []
    for agent_id, ws in _ws_connections.items():
        try:
            await ws.send_json(payload)
        except Exception:
            disconnected.append(agent_id)
    for agent_id in disconnected:
        _ws_connections.pop(agent_id, None)
        task = _push_tasks.pop(agent_id, None)
        if task:
            task.cancel()
