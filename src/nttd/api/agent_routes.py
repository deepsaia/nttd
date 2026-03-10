from fastapi import APIRouter, HTTPException

from nttd.api.dependencies import agent_registry
from nttd.schemas.agent import AgentRegistration, AgentStatus, Subscription

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/connect", response_model=AgentStatus)
def connect_agent(registration: AgentRegistration) -> AgentStatus:
    return agent_registry.connect(registration)


@router.post("/{agent_id}/disconnect")
def disconnect_agent(agent_id: str) -> dict[str, bool]:
    removed = agent_registry.disconnect(agent_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return {"disconnected": True}


@router.get("/{agent_id}/status", response_model=AgentStatus)
def get_agent_status(agent_id: str) -> AgentStatus:
    status = agent_registry.get(agent_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return status


@router.get("/list", response_model=list[AgentStatus])
def list_agents() -> list[AgentStatus]:
    return agent_registry.list_agents()


@router.post("/{agent_id}/subscriptions")
def add_subscription(agent_id: str, subscription: Subscription) -> dict[str, bool]:
    added = agent_registry.add_subscription(agent_id, subscription)
    if not added:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    return {"subscribed": True}


@router.delete("/{agent_id}/subscriptions/{channel}")
def remove_subscription(agent_id: str, channel: str) -> dict[str, bool]:
    removed = agent_registry.remove_subscription(agent_id, channel)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Subscription {channel} not found for agent {agent_id}")
    return {"removed": True}


@router.get("/{agent_id}/subscriptions", response_model=list[Subscription])
def list_subscriptions(agent_id: str) -> list[Subscription]:
    return agent_registry.get_subscriptions(agent_id)
