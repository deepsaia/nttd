"""Base adapter interface for framework-specific LLM callers."""

from __future__ import annotations

import abc
from typing import Any, Protocol


class ToolExecutor(Protocol):
    """Callable that executes an observation tool and returns a JSON string."""

    async def __call__(self, tool_name: str, arguments: dict[str, Any]) -> str: ...


class MessageLogger(Protocol):
    """Callable that logs a message role+content to the agent's conversation file."""

    def __call__(self, role: str, content: str) -> None: ...


class BaseAdapter(abc.ABC):
    """Abstract base for framework adapters that call an LLM.

    Each adapter wraps a specific LLM SDK (OpenAI, LangChain, etc.)
    and implements the ``decide`` method to turn an observation + instructions
    into raw agent output (text or structured action list).
    """

    @abc.abstractmethod
    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        message_logger: MessageLogger | None = None,
    ) -> str:
        """Call the LLM with the observation and instructions.

        Args:
            observation: Game state snapshot (compact or full).
            instructions: System prompt for the agent.
            observation_tools: Optional OpenAI-format tool definitions.
            tool_executor: Callable to execute tools when the LLM requests them.
            message_logger: Optional callback to log conversation messages.

        Returns:
            Raw LLM output text containing the action list.
        """

    async def close(self) -> None:
        """Clean up resources (e.g., HTTP clients)."""
