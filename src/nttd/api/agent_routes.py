"""Session-scoped agent routes: connect, disconnect, subscriptions."""

from fastapi import APIRouter, HTTPException

import nttd.api.dependencies as deps
from nttd.schemas.agent import AgentRegistration, AgentStatus, Subscription
from nttd.state.snapshot_broker import AgentSnapshotBroker

router = APIRouter(prefix="/sessions/{session_id}/agents", tags=["agents"])


@router.post("/connect", response_model=AgentStatus)
def connect_agent(session_id: str, registration: AgentRegistration) -> AgentStatus:
    runtime = deps.get_runtime(session_id)
    status = runtime.agent_registry.connect(registration)
    runtime.snapshot_broker_registry[registration.agent_id] = AgentSnapshotBroker()
    return status


@router.post("/{agent_id}/disconnect")
def disconnect_agent(session_id: str, agent_id: str) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    removed = runtime.agent_registry.disconnect(agent_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    runtime.snapshot_broker_registry.pop(agent_id, None)
    return {"disconnected": True}


@router.get("/{agent_id}/status", response_model=AgentStatus)
def get_agent_status(session_id: str, agent_id: str) -> AgentStatus:
    runtime = deps.get_runtime(session_id)
    status = runtime.agent_registry.get(agent_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return status


@router.get("/list", response_model=list[AgentStatus])
def list_agents(session_id: str) -> list[AgentStatus]:
    runtime = deps.get_runtime(session_id)
    return runtime.agent_registry.list_agents()


@router.post("/{agent_id}/subscriptions")
def add_subscription(session_id: str, agent_id: str, subscription: Subscription) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    added = runtime.agent_registry.add_subscription(agent_id, subscription)
    if not added:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return {"subscribed": True}


@router.delete("/{agent_id}/subscriptions/{channel}")
def remove_subscription(session_id: str, agent_id: str, channel: str) -> dict[str, bool]:
    runtime = deps.get_runtime(session_id)
    removed = runtime.agent_registry.remove_subscription(agent_id, channel)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Subscription {channel} not found for agent {agent_id}")
    return {"removed": True}


@router.get("/{agent_id}/subscriptions", response_model=list[Subscription])
def list_subscriptions(session_id: str, agent_id: str) -> list[Subscription]:
    runtime = deps.get_runtime(session_id)
    return runtime.agent_registry.get_subscriptions(agent_id)
