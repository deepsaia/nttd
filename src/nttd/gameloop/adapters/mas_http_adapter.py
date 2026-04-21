"""HTTP/SSE client adapter for external MAS servers.

Connects to any MAS framework that exposes HTTP endpoints:
- POST endpoint: send observation, receive actions
- SSE stream_endpoint (optional): stream intermediate agent messages for logging

Works with LangGraph (LangServe), Agno (Agent OS), CrewAI (AMP), or any
custom FastAPI wrapper around a MAS framework.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from nttd.gameloop.adapters.base import BaseAdapter, MessageLogger, ToolExecutor
from nttd.gameloop.schemas import MASTransportConfig

logger = logging.getLogger(__name__)


class MASHttpAdapter(BaseAdapter):
    """Adapter that connects to an external MAS server via HTTP.

    Sends game observations as JSON POST requests and receives action lists.
    Optionally streams intermediate agent messages via SSE for conversation logging.
    """

    def __init__(self, transport_config: MASTransportConfig) -> None:
        self._config = transport_config
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            auth_type = self._config.auth.type.lower()
            if auth_type == "bearer":
                token = os.environ.get(self._config.auth.token_env, "")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
            elif auth_type == "api_key":
                token = os.environ.get(self._config.auth.token_env, "")
                if token:
                    headers["X-API-Key"] = token

            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self._config.timeout, connect=10.0),
            )
        return self._client

    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        message_logger: MessageLogger | None = None,
    ) -> str:
        client = self._get_client()

        payload: dict[str, Any] = {
            "observation": observation,
            "instructions": instructions,
        }
        if observation_tools:
            payload["tools"] = observation_tools

        if message_logger:
            message_logger("SYSTEM", instructions)
            message_logger("USER (observation)", json.dumps(observation, indent=2))

        endpoint = self._config.endpoint
        if not endpoint:
            raise RuntimeError("MAS HTTP adapter: endpoint URL not configured")

        last_error: Exception | None = None
        for attempt in range(self._config.retry_count + 1):
            try:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                break
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self._config.retry_count:
                    import asyncio
                    wait = self._config.retry_backoff * (2 ** attempt)
                    logger.warning(
                        "MAS HTTP attempt %d failed (%s), retrying in %.1fs",
                        attempt + 1, exc, wait,
                    )
                    await asyncio.sleep(wait)
        else:
            logger.error("MAS HTTP all %d attempts failed", self._config.retry_count + 1)
            if message_logger:
                message_logger("ERROR", str(last_error))
            return "[]"

        body = response.json()
        actions = body.get("actions", body)

        if isinstance(actions, list):
            output = json.dumps(actions)
        elif isinstance(actions, str):
            output = actions
        else:
            output = json.dumps(actions)

        if message_logger:
            message_logger("ASSISTANT (MAS response)", output)

        # Stream intermediate messages if stream_endpoint is configured
        if self._config.stream_endpoint and message_logger:
            await self._stream_log(payload, message_logger)

        return output

    async def _stream_log(
        self,
        payload: dict[str, Any],
        message_logger: MessageLogger,
    ) -> None:
        """Connect to SSE stream endpoint and log intermediate agent messages.

        This is best-effort: failures here don't affect the action response.
        """
        client = self._get_client()
        try:
            async with client.stream(
                "POST",
                self._config.stream_endpoint,
                json=payload,
                timeout=httpx.Timeout(self._config.timeout, connect=10.0),
            ) as response:
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            event = json.loads(data_str)
                            agent_id = event.get("agent_id", "")
                            role = event.get("role", event.get("type", "event"))
                            content = event.get("content", data_str)
                            prefix = f"[{agent_id}] " if agent_id else ""
                            message_logger(f"{prefix}{role}", str(content))
                        except json.JSONDecodeError:
                            message_logger("STREAM", data_str)
        except Exception:
            logger.debug("MAS stream logging failed (non-critical)", exc_info=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
