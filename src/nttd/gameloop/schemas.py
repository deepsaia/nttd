"""Pydantic models for gameloop agent configuration, status, and cycle records."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MASAuthConfig(BaseModel):
    """Authentication settings for external MAS connections."""

    type: str = "none"
    token_env: str = ""


class MASTransportConfig(BaseModel):
    """Transport configuration for connecting to a MAS server.

    Supports three transports:
    - "custom": in-process sub-agent graph (uses config_path for HOCON definition)
    - "http": external MAS server via HTTP/HTTPS (POST observations, receive actions)
    - "mcp": external MAS server via Model Context Protocol
    """

    transport: str = "custom"
    endpoint: str = ""
    stream_endpoint: str = ""
    config_path: str = ""
    auth: MASAuthConfig = Field(default_factory=MASAuthConfig)
    timeout: float = 60.0
    retry_count: int = 2
    retry_backoff: float = 1.0


class AgentConfig(BaseModel):
    """Configuration for registering an agent with the gameloop."""

    agent_id: str
    company_id: int = Field(ge=0, le=14)
    name: str = ""
    agent_type: str = "road"
    framework: str = "openai"
    model: str = "gpt-4o"
    instructions: str = ""
    observation_mode: str = "compact"
    snapshot_class: str = ""
    include_finance: bool = False
    poll_interval: float = Field(default=5.0, ge=0.5)
    observation_tools: bool = True
    max_actions_per_cycle: int = Field(default=10, ge=1)
    max_history_cycles: int = Field(default=10, ge=1)
    api_key_env: str = "OPENAI_API_KEY"
    mas_config: str = ""
    mas_transport: MASTransportConfig = Field(default_factory=MASTransportConfig)

    @property
    def effective_snapshot_class(self) -> str:
        """Return snapshot_class if set, otherwise fall back to observation_mode."""
        return self.snapshot_class or self.observation_mode


class ConnectionStatus(BaseModel):
    """Status snapshot of a single agent connection."""

    connection_id: str
    agent_id: str
    company_id: int
    framework: str
    model: str
    status: str = "registered"
    cycle_count: int = 0
    total_actions: int = 0
    successful_actions: int = 0
    failed_actions: int = 0
    avg_cycle_ms: float = 0.0
    avg_decide_ms: float = 0.0
    last_error: str = ""


class CycleRecord(BaseModel):
    """Record of a single agent cycle for telemetry."""

    connection_id: str
    session_id: str
    cycle_number: int
    game_date: int = 0
    observe_ms: float = 0.0
    decide_ms: float = 0.0
    execute_ms: float = 0.0
    total_ms: float = 0.0
    actions_proposed: int = 0
    actions_executed: int = 0
    actions_succeeded: int = 0
    actions_failed: int = 0
    observation_size_bytes: int = 0
    balance: int = 0
    income: int = 0
    company_value: int = 0
    balance_delta: int = 0
    vehicles_running: int = 0
