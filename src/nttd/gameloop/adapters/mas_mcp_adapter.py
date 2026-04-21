"""MCP (Model Context Protocol) client adapter for external MAS servers.

Connects to any MAS that exposes an MCP server endpoint (e.g., Neuro-SAN).
Uses the MCP client SDK to discover tools, send observations, and receive actions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nttd.gameloop.adapters.base import BaseAdapter, MessageLogger, ToolExecutor
from nttd.gameloop.schemas import MASTransportConfig

logger = logging.getLogger(__name__)


class MASMcpAdapter(BaseAdapter):
    """Adapter that connects to an external MAS server via MCP.

    Sends game observations as context and invokes the MAS's "decide" tool.
    Streams notifications for conversation logging.
    """

    def __init__(self, transport_config: MASTransportConfig) -> None:
        self._config = transport_config
        self._session: Any = None
        self._transport: Any = None

    async def _ensure_session(self) -> Any:
        """Lazily connect to the MCP server and return the session."""
        if self._session is not None:
            return self._session

        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError(
                "MCP SDK not installed. Install with: pip install mcp"
            ) from exc

        endpoint = self._config.endpoint
        if not endpoint:
            raise RuntimeError("MAS MCP adapter: endpoint not configured")

        if endpoint.startswith("stdio://"):
            cmd = endpoint[len("stdio://"):]
            parts = cmd.split()
            self._transport = stdio_client(parts[0], args=parts[1:] if len(parts) > 1 else [])
        else:
            self._transport = sse_client(endpoint)

        read_stream, write_stream = await self._transport.__aenter__()
        self._session = ClientSession(read_stream, write_stream)
        await self._session.__aenter__()
        await self._session.initialize()

        logger.info("MCP session established to %s", endpoint)
        return self._session

    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        message_logger: MessageLogger | None = None,
    ) -> str:
        session = await self._ensure_session()

        if message_logger:
            message_logger("SYSTEM", instructions)
            message_logger("USER (observation)", json.dumps(observation, indent=2))

        payload = {
            "observation": json.dumps(observation),
            "instructions": instructions,
        }
        if observation_tools:
            payload["tools"] = json.dumps(observation_tools)

        try:
            result = await session.call_tool("decide", arguments=payload)

            if result.isError:
                error_text = str(result.content)
                logger.warning("MCP decide tool returned error: %s", error_text)
                if message_logger:
                    message_logger("ERROR", error_text)
                return "[]"

            output_parts = []
            for content_block in result.content:
                if hasattr(content_block, "text"):
                    output_parts.append(content_block.text)

            output = "".join(output_parts) if output_parts else "[]"

            if message_logger:
                message_logger("ASSISTANT (MCP response)", output)

            return output

        except Exception as exc:
            logger.error("MCP decide call failed: %s", exc)
            if message_logger:
                message_logger("ERROR", str(exc))
            return "[]"

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                logger.debug("MCP session close error", exc_info=True)
            self._session = None
        if self._transport is not None:
            try:
                await self._transport.__aexit__(None, None, None)
            except Exception:
                logger.debug("MCP transport close error", exc_info=True)
            self._transport = None
