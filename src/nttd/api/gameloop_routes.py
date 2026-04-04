"""REST API endpoints for gameloop agent management.

All endpoints are session-scoped: /sessions/{session_id}/gameloop/...
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import nttd.api.dependencies as deps
from nttd.gameloop.schemas import AgentConfig, ConnectionStatus, CycleRecord

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/sessions/{session_id}/gameloop",
    tags=["gameloop"],
)


@router.post("/agents/register")
async def register_agent(session_id: str, config: AgentConfig) -> dict[str, Any]:
    """Register an agent with the gameloop. Returns the connection_id."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized for this session")
    try:
        connection_id = await runtime.gameloop_manager.register_agent(config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"connection_id": connection_id, "agent_id": config.agent_id}


@router.post("/agents/{agent_id}/start")
async def start_agent(session_id: str, agent_id: str) -> dict[str, str]:
    """Start an agent's cycle loop."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized")
    try:
        await runtime.gameloop_manager.start_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "started", "agent_id": agent_id}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(session_id: str, agent_id: str) -> dict[str, str]:
    """Stop an agent's cycle loop."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized")
    try:
        await runtime.gameloop_manager.stop_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "stopped", "agent_id": agent_id}


@router.get("/agents", response_model=list[ConnectionStatus])
async def list_agents(session_id: str) -> list[ConnectionStatus]:
    """List all agent connections with status."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized")
    return runtime.gameloop_manager.list_connections()


@router.get("/agents/{agent_id}/status", response_model=ConnectionStatus)
async def get_agent_status(session_id: str, agent_id: str) -> ConnectionStatus:
    """Get detailed status for a specific agent."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized")
    try:
        return runtime.gameloop_manager.get_status(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/cycles", response_model=list[CycleRecord])
async def get_agent_cycles(session_id: str, agent_id: str, limit: int = 50) -> list[CycleRecord]:
    """Get recent cycle records for an agent."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized")
    try:
        return runtime.gameloop_manager.get_recent_cycles(agent_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/status")
async def get_gameloop_status(session_id: str) -> dict[str, Any]:
    """Get overall gameloop status for this session."""
    runtime = deps.get_runtime(session_id)
    if runtime.gameloop_manager is None:
        raise HTTPException(status_code=503, detail="Gameloop not initialized")
    return runtime.gameloop_manager.get_overall_status()
