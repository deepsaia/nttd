"""Session-scoped WebSocket routes for admin console and agent push notifications."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import nttd.api.dependencies as deps
from nttd.schemas.snapshot import StateSnapshot

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Per-session WebSocket state
_ws_connections: dict[str, dict[str, WebSocket]] = {}  # session_id -> {agent_id: ws}
_push_tasks: dict[str, dict[str, asyncio.Task[None]]] = {}  # session_id -> {agent_id: task}
_admin_ws_connections: dict[str, list[WebSocket]] = {}  # session_id -> [ws]


@router.websocket("/ws/{session_id}/admin")
async def admin_websocket(websocket: WebSocket, session_id: str) -> None:
    """Unauthenticated WebSocket for the admin console: receives event notifications."""
    await websocket.accept()
    _admin_ws_connections.setdefault(session_id, []).append(websocket)
    logger.info("Admin WebSocket connected for session %s", session_id)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("Admin WebSocket disconnected for session %s", session_id)
    finally:
        conns = _admin_ws_connections.get(session_id, [])
        if websocket in conns:
            conns.remove(websocket)


@router.websocket("/ws/{session_id}/{agent_id}")
async def agent_websocket(websocket: WebSocket, session_id: str, agent_id: str) -> None:
    runtime = deps.get_runtime(session_id)
    status = runtime.agent_registry.get(agent_id)
    if status is None:
        await websocket.close(code=4004, reason=f"Agent {agent_id} not connected")
        return

    await websocket.accept()
    _ws_connections.setdefault(session_id, {})[agent_id] = websocket
    logger.info("WebSocket connected: session=%s agent=%s", session_id, agent_id)

    push_task = asyncio.create_task(_push_loop(session_id, agent_id, websocket))
    _push_tasks.setdefault(session_id, {})[agent_id] = push_task

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s agent=%s", session_id, agent_id)
    finally:
        push_task.cancel()
        session_tasks = _push_tasks.get(session_id, {})
        session_tasks.pop(agent_id, None)
        session_conns = _ws_connections.get(session_id, {})
        session_conns.pop(agent_id, None)


async def _push_loop(session_id: str, agent_id: str, websocket: WebSocket) -> None:
    """Deliver heartbeat triggers to agents."""
    runtime = deps.get_runtime(session_id)
    broker = runtime.snapshot_broker_registry.get(agent_id)
    if broker is None:
        return

    while True:
        try:
            try:
                snapshot = await asyncio.wait_for(
                    broker.wait_for_snapshot(), timeout=20.0
                )
                await websocket.send_json({
                    "type": "heartbeat",
                    "game_date": snapshot.game.game_date,
                    "paused": snapshot.game.paused,
                    "mode": snapshot.game.mode,
                    "companies": len(snapshot.companies),
                    "towns": len(snapshot.towns),
                    "vehicles": len(snapshot.vehicles),
                })
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("Push loop error for session=%s agent=%s: stopping", session_id, agent_id, exc_info=True)
            break


async def broadcast_snapshot(session_id: str, snapshot: StateSnapshot) -> None:
    """Push a snapshot to all registered agent brokers for a session."""
    mgr = deps.session_manager
    if mgr is None:
        return
    runtime = mgr.get_runtime(session_id)
    if runtime is None:
        return

    for agent_id, broker in runtime.snapshot_broker_registry.items():
        await broker.push_snapshot(snapshot)

    # Push to WebSockets whose broker may be missing
    session_conns = _ws_connections.get(session_id, {})
    disconnected = []
    for agent_id, ws in session_conns.items():
        if agent_id not in runtime.snapshot_broker_registry:
            try:
                await ws.send_json({"type": "snapshot", "data": snapshot.model_dump()})
            except Exception:
                disconnected.append(agent_id)
    for agent_id in disconnected:
        session_conns.pop(agent_id, None)
        task = _push_tasks.get(session_id, {}).pop(agent_id, None)
        if task:
            task.cancel()

    # Notify admin console WebSocket connections
    admin_conns = _admin_ws_connections.get(session_id, [])
    dead: list[WebSocket] = []
    for ws in admin_conns:
        try:
            await ws.send_json({
                "type": "snapshot",
                "game_date": snapshot.game.game_date,
                "companies": len(snapshot.companies),
            })
        except Exception:
            dead.append(ws)
    for ws in dead:
        admin_conns.remove(ws)
