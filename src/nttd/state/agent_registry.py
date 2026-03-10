from nttd.schemas.agent import AgentRegistration, AgentStatus, Subscription


class AgentRegistry:
    """Tracks connected agents and their subscriptions."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}

    def connect(self, registration: AgentRegistration) -> AgentStatus:
        self._agents[registration.agent_id] = registration
        return self._to_status(registration)

    def disconnect(self, agent_id: str) -> bool:
        return self._agents.pop(agent_id, None) is not None

    def get(self, agent_id: str) -> AgentStatus | None:
        reg = self._agents.get(agent_id)
        if reg is None:
            return None
        return self._to_status(reg)

    def list_agents(self) -> list[AgentStatus]:
        return [self._to_status(reg) for reg in self._agents.values()]

    def add_subscription(self, agent_id: str, subscription: Subscription) -> bool:
        reg = self._agents.get(agent_id)
        if reg is None:
            return False
        reg.subscriptions.append(subscription)
        return True

    def remove_subscription(self, agent_id: str, channel: str) -> bool:
        reg = self._agents.get(agent_id)
        if reg is None:
            return False
        before = len(reg.subscriptions)
        reg.subscriptions = [s for s in reg.subscriptions if s.channel != channel]
        return len(reg.subscriptions) < before

    def get_subscriptions(self, agent_id: str) -> list[Subscription]:
        reg = self._agents.get(agent_id)
        if reg is None:
            return []
        return list(reg.subscriptions)

    def _to_status(self, reg: AgentRegistration) -> AgentStatus:
        return AgentStatus(
            agent_id=reg.agent_id,
            name=reg.name,
            connected=True,
            company_scope=reg.company_scope,
            subscriptions=reg.subscriptions,
        )
