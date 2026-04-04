"""GameloopManager — manages all agent connections for a single session."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nttd.gameloop.adapters.base import BaseAdapter
from nttd.gameloop.adapters.langchain_adapter import LangChainAdapter
from nttd.gameloop.adapters.openai_adapter import OpenAIAdapter
from nttd.gameloop.adapters.passthrough_adapter import PassthroughAdapter
from nttd.gameloop.connection import AgentConnection
from nttd.gameloop.schemas import AgentConfig, ConnectionStatus, CycleRecord
from nttd.schemas.agent import AgentRegistration

if TYPE_CHECKING:
    from nttd.runtime.session_runtime import SessionRuntime

logger = logging.getLogger(__name__)

_MAX_COMPANIES = 15


class GameloopManager:
    """Manages agent connections for one session.

    One instance per session, stored on SessionRuntime.
    Handles registration, start/stop, and lifecycle of agent connections.
    """

    def __init__(self, runtime: SessionRuntime) -> None:
        self.runtime = runtime
        self.connections: dict[str, AgentConnection] = {}
        self._agent_to_connection: dict[str, str] = {}

    def _make_connection_id(self, config: AgentConfig) -> str:
        return f"{self.runtime.session_id}:{config.company_id}:{config.agent_id}"

    async def register_agent(self, config: AgentConfig) -> str:
        """Register an agent, create its connection, return connection_id.

        Validates:
          - company_id is in range [0, 14]
          - No other agent already controls this company
          - agent_id is unique within this session
        """
        if config.company_id < 0 or config.company_id >= _MAX_COMPANIES:
            raise ValueError(
                f"company_id must be 0-{_MAX_COMPANIES - 1}, got {config.company_id}"
            )

        connection_id = self._make_connection_id(config)
        if connection_id in self.connections:
            raise ValueError(f"Agent {config.agent_id} already registered for company {config.company_id}")

        # Check no other agent on same company
        for conn in self.connections.values():
            if conn.config.company_id == config.company_id:
                raise ValueError(
                    f"Company {config.company_id} already has agent {conn.config.agent_id}"
                )

        # Create adapter
        adapter = self._create_adapter(config)

        # Create connection
        connection = AgentConnection(
            connection_id=connection_id,
            config=config,
            runtime=self.runtime,
            adapter=adapter,
        )

        self.connections[connection_id] = connection
        self._agent_to_connection[config.agent_id] = connection_id

        # Also register in the agent_registry for visibility
        self.runtime.agent_registry.connect(AgentRegistration(
            agent_id=config.agent_id,
            name=config.name or f"{config.framework}:{config.model}",
            company_scope=[config.company_id],
        ))

        logger.info(
            "Registered agent %s (company=%d, framework=%s) → %s",
            config.agent_id, config.company_id, config.framework, connection_id,
        )
        return connection_id

    async def start_agent(self, agent_id: str) -> None:
        """Start an agent's cycle loop."""
        conn = self._get_connection(agent_id)
        conn.start()

    async def stop_agent(self, agent_id: str) -> None:
        """Stop an agent's cycle loop."""
        conn = self._get_connection(agent_id)
        await conn.stop()

    async def stop_all(self) -> None:
        """Stop all agent loops. Called on session end."""
        logger.info("Stopping all agents for session %s", self.runtime.session_id)
        for conn in self.connections.values():
            try:
                await conn.stop()
            except Exception:
                logger.exception("Error stopping agent %s", conn.config.agent_id)

    async def unregister_agent(self, agent_id: str) -> None:
        """Stop and remove an agent connection."""
        conn = self._get_connection(agent_id)
        await conn.stop()
        del self.connections[conn.connection_id]
        del self._agent_to_connection[agent_id]
        self.runtime.agent_registry.disconnect(agent_id)

    def get_status(self, agent_id: str) -> ConnectionStatus:
        """Get the status of a specific agent."""
        conn = self._get_connection(agent_id)
        return conn.to_status()

    def list_connections(self) -> list[ConnectionStatus]:
        """List all connections with their current status."""
        return [conn.to_status() for conn in self.connections.values()]

    def get_recent_cycles(self, agent_id: str, limit: int = 50) -> list[CycleRecord]:
        """Get recent cycle records for an agent."""
        conn = self._get_connection(agent_id)
        cycles = list(conn.tracker.recent_cycles)
        return cycles[-limit:]

    def get_overall_status(self) -> dict[str, Any]:
        """Get summary status of the gameloop for this session."""
        total_agents = len(self.connections)
        running = sum(1 for c in self.connections.values() if c.status == "running")
        total_cycles = sum(c.tracker.cycle_count for c in self.connections.values())
        total_actions = sum(c.tracker.total_actions for c in self.connections.values())
        return {
            "session_id": self.runtime.session_id,
            "total_agents": total_agents,
            "running_agents": running,
            "total_cycles": total_cycles,
            "total_actions": total_actions,
        }

    def _get_connection(self, agent_id: str) -> AgentConnection:
        connection_id = self._agent_to_connection.get(agent_id)
        if connection_id is None or connection_id not in self.connections:
            raise KeyError(f"Agent {agent_id} not found in session {self.runtime.session_id}")
        return self.connections[connection_id]

    def _create_adapter(self, config: AgentConfig) -> BaseAdapter:
        """Create the appropriate framework adapter based on config."""
        framework = config.framework.lower()

        if framework == "passthrough":
            return PassthroughAdapter()
        if framework == "openai":
            return OpenAIAdapter(
                model=config.model,
                api_key_env=config.api_key_env,
            )
        if framework == "langchain":
            return LangChainAdapter(
                model=config.model,
                api_key_env=config.api_key_env,
            )

        raise ValueError(f"Unknown framework: {config.framework}. Use: openai, langchain, passthrough")
