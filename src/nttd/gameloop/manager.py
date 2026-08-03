"""GameloopManager — manages all agent connections for a single session."""

from __future__ import annotations

import logging
import os
from pathlib import Path
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

_MAS_FRAMEWORKS = frozenset({"mas"})

_MAX_COMPANIES = 15


async def _resolve_neuro_san_model(endpoint: str) -> str | None:
    """Extract model name from neuro-san HOCON via AGENT_MANIFEST_FILE env var.

    Parses the agent network name from the endpoint URL, finds the HOCON
    in the same directory as the manifest, and reads llm_config.model_name.
    Returns None if anything fails (missing env var, file not found, etc.).
    """
    manifest = os.environ.get("AGENT_MANIFEST_FILE", "")
    if not manifest:
        return None

    registries_dir = Path(manifest).parent

    parts = endpoint.rstrip("/").split("/")
    try:
        idx = parts.index("streaming_chat")
        network_name = parts[idx - 1]
    except (ValueError, IndexError):
        return None

    hocon_path = registries_dir / f"{network_name}.hocon"
    if not hocon_path.exists():
        return None

    try:
        from neuro_san.internals.persistence.abstract_async_config_restorer import (
            AbstractAsyncConfigRestorer,
        )

        restorer = AbstractAsyncConfigRestorer(
            file_purpose="get_agent_network_definition", must_exist=True,
        )
        config = await restorer.async_restore(file_reference=str(hocon_path))
        llm_config = config.get("llm_config", {})
        model_name = llm_config.get("model_name")
        if model_name:
            provider = llm_config.get("class", "")
            return f"{model_name} ({provider})" if provider else model_name
    except Exception:
        logger.debug("Could not resolve model from HOCON %s", hocon_path, exc_info=True)
    return None


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
          - agent_id is unique within this session

        Multiple agents can share the same company_id.
        """
        if config.company_id < 0 or config.company_id >= _MAX_COMPANIES:
            raise ValueError(
                f"company_id must be 0-{_MAX_COMPANIES - 1}, got {config.company_id}"
            )

        connection_id = self._make_connection_id(config)
        if connection_id in self.connections:
            raise ValueError(f"Agent {config.agent_id} already registered for company {config.company_id}")

        # A scored session imposes its own pacing and budget limits. These fields
        # arrive on the contestant-supplied config, so without this every
        # contestant would set their own budget.
        changed = self.runtime.fairness.apply_to(config)
        if changed:
            logger.info(
                "Agent %s: scenario fairness limits override %s",
                config.agent_id, "; ".join(changed),
            )

        # Resolve model name from HOCON for neuro-san MAS agents
        if (
            config.nttd_framework.lower() in _MAS_FRAMEWORKS
            and config.mas_transport.mas_framework.lower() == "neuro_san"
        ):
            resolved = await _resolve_neuro_san_model(config.mas_transport.endpoint)
            if resolved:
                config.model = resolved
                logger.info("Resolved model from HOCON: %s", resolved)

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
            name=config.name or f"{config.nttd_framework}:{config.model}",
            company_scope=[config.company_id],
        ))

        logger.info(
            "Registered agent %s (company=%d, nttd_framework=%s) → %s",
            config.agent_id, config.company_id, config.nttd_framework, connection_id,
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

    def participant_summary(self) -> dict[int, dict[str, Any]]:
        """Aggregate each company's contestant detail for the result record.

        Keyed by company_id. Token counts and cost are summed from the tracker's
        retained cycle records, so a long run whose early cycles have aged out of
        the ring buffer reports a partial total -- flagged as estimated rather
        than presented as exact.

        When several agents share a company (the multi-agent shape) their actions
        and spend are combined, since the company is what gets scored.
        """
        summary: dict[int, dict[str, Any]] = {}
        for conn in self.connections.values():
            cid = conn.config.company_id
            entry = summary.setdefault(cid, {
                "participant_type": "agent",
                "agent_id": "",
                "nttd_framework": "",
                "model": "",
                "total_actions": 0,
                "successful_actions": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_cost": 0.0,
                "cost_is_estimated": False,
            })

            # Join ids and models so a shared company shows every contributor.
            entry["agent_id"] = "+".join(
                filter(None, [entry["agent_id"], conn.config.agent_id])
            )
            if conn.config.nttd_framework not in entry["nttd_framework"]:
                entry["nttd_framework"] = "+".join(
                    filter(None, [entry["nttd_framework"], conn.config.nttd_framework])
                )
            if conn.config.model not in entry["model"]:
                entry["model"] = "+".join(filter(None, [entry["model"], conn.config.model]))

            entry["total_actions"] += conn.tracker.total_actions
            entry["successful_actions"] += conn.tracker.successful_actions

            cycles = list(conn.tracker.recent_cycles)
            entry["prompt_tokens"] += sum(c.prompt_tokens for c in cycles)
            entry["completion_tokens"] += sum(c.completion_tokens for c in cycles)
            entry["total_cost"] += sum(c.total_cost for c in cycles)
            # The ring buffer caps retained cycles, so totals are only exact when
            # every cycle of the run is still held.
            if conn.tracker.cycle_count > len(cycles):
                entry["cost_is_estimated"] = True

        return summary

    def _get_connection(self, agent_id: str) -> AgentConnection:
        connection_id = self._agent_to_connection.get(agent_id)
        if connection_id is None or connection_id not in self.connections:
            raise KeyError(f"Agent {agent_id} not found in session {self.runtime.session_id}")
        return self.connections[connection_id]

    def _create_adapter(self, config: AgentConfig) -> BaseAdapter:
        """Create the appropriate framework adapter based on config."""
        nttd_framework = config.nttd_framework.lower()

        if nttd_framework == "passthrough":
            return PassthroughAdapter()
        if nttd_framework == "openai":
            return OpenAIAdapter(
                model=config.model,
                api_key_env=config.api_key_env,
            )
        if nttd_framework == "langchain":
            return LangChainAdapter(
                model=config.model,
                api_key_env=config.api_key_env,
            )
        if nttd_framework in _MAS_FRAMEWORKS:
            return self._create_mas_adapter(config)

        raise ValueError(
            f"Unknown nttd_framework: {config.nttd_framework}. "
            f"Use: openai, langchain, passthrough, mas"
        )

    def _create_mas_adapter(self, config: AgentConfig) -> BaseAdapter:
        """Create the right MAS adapter based on transport config."""
        protocol = config.mas_transport.protocol.lower()

        if protocol == "custom":
            from nttd.gameloop.adapters.mas_adapter import MASAdapter

            config_path = config.mas_transport.config_path or config.mas_config
            if not config_path:
                raise ValueError(
                    f"Agent {config.agent_id}: MAS custom protocol requires "
                    f"mas_transport.config_path or mas_config"
                )
            return MASAdapter(
                mas_config_path=config_path,
                default_model=config.model,
                api_key_env=config.api_key_env,
            )

        if protocol == "http":
            from nttd.gameloop.adapters.mas_http_adapter import MASHttpAdapter

            if not config.mas_transport.endpoint:
                raise ValueError(
                    f"Agent {config.agent_id}: MAS HTTP protocol requires "
                    f"mas_transport.endpoint"
                )
            return MASHttpAdapter(
                transport_config=config.mas_transport,
                session_id=self.runtime.session_id,
                company_id=config.company_id,
            )

        if protocol == "mcp":
            from nttd.gameloop.adapters.mas_mcp_adapter import MASMcpAdapter

            if not config.mas_transport.endpoint:
                raise ValueError(
                    f"Agent {config.agent_id}: MAS MCP protocol requires "
                    f"mas_transport.endpoint"
                )
            return MASMcpAdapter(transport_config=config.mas_transport)

        raise ValueError(
            f"Agent {config.agent_id}: Unknown MAS protocol: {protocol}. "
            f"Use: custom, http, mcp"
        )
