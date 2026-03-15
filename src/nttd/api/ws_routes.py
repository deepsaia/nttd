import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nttd.api.dependencies import agent_registry, snapshot_broker_registry
from nttd.schemas.snapshot import StateSnapshot

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
    """Push snapshots to agent when broker delivers the next heartbeat snapshot."""
    broker = snapshot_broker_registry.get(agent_id)
    if broker is None:
        return

    while True:
        try:
            snapshot = await broker.wait_for_snapshot()
            await websocket.send_json({
                "type": "snapshot",
                "data": snapshot.model_dump(),
            })
        except asyncio.CancelledError:
            break
        except Exception:
            break


async def broadcast_snapshot(snapshot: StateSnapshot) -> None:
    """Push a snapshot to all registered agent brokers. Called by orchestrator observers."""
    for agent_id, broker in snapshot_broker_registry.items():
        await broker.push_snapshot(snapshot)

    # Also push directly to any connected WebSockets whose broker may be missing
    disconnected = []
    for agent_id, ws in _ws_connections.items():
        if agent_id not in snapshot_broker_registry:
            try:
                await ws.send_json({"type": "snapshot", "data": snapshot.model_dump()})
            except Exception:
                disconnected.append(agent_id)
    for agent_id in disconnected:
        _ws_connections.pop(agent_id, None)
        task = _push_tasks.pop(agent_id, None)
        if task:
            task.cancel()
