from enum import StrEnum

from pydantic import BaseModel


class SubscriptionType(StrEnum):
    ENTITY = "entity"
    EVENT = "event"
    DERIVED = "derived"


class Subscription(BaseModel):
    channel: str
    subscription_type: SubscriptionType = SubscriptionType.ENTITY
    cadence: int = 1


class AgentRegistration(BaseModel):
    agent_id: str
    name: str = ""
    company_scope: list[int] = []
    subscriptions: list[Subscription] = []


class AgentStatus(BaseModel):
    agent_id: str
    name: str = ""
    connected: bool = True
    company_scope: list[int] = []
    subscriptions: list[Subscription] = []
