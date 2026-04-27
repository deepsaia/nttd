"""HTTP client adapter for external MAS servers.

Connects to any MAS framework that exposes HTTP endpoints.
Routes to the appropriate handler based on mas_framework:

- "generic": POST {observation, instructions} -> {actions: [...]}
  Works with LangGraph (LangServe), Agno (Agent OS), CrewAI, or any
  custom FastAPI wrapper.

- "neuro_san": POST streaming_chat request -> streaming JSON lines
  Speaks neuro-san's native /api/v1/{agent}/streaming_chat endpoint.
  Sends observation as sly_data, reads actions from the final
  AGENT_FRAMEWORK response.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor

from nttd.gameloop.adapters.base import BaseAdapter, MessageLogger, ToolExecutor
from nttd.gameloop.schemas import MASTransportConfig, TokenUsage

logger = logging.getLogger(__name__)


def _parse_token_structure(structure: dict[str, Any]) -> TokenUsage | None:
    """Extract TokenUsage from a neuro-san token accounting structure dict."""
    if not isinstance(structure, dict) or "total_tokens" not in structure:
        return None
    models_dict = structure.get("models", {})
    model_name = ""
    provider_name = ""
    if models_dict:
        provider_name = next(iter(models_dict), "")
        provider_models = models_dict.get(provider_name, {})
        if provider_models:
            model_name = next(iter(provider_models), "")
    return TokenUsage(
        prompt_tokens=structure.get("prompt_tokens", 0),
        completion_tokens=structure.get("completion_tokens", 0),
        total_tokens=structure.get("total_tokens", 0),
        total_cost=structure.get("total_cost", 0.0),
        model=model_name,
        provider=provider_name,
    )


class MASHttpAdapter(BaseAdapter):
    """Adapter that connects to an external MAS server via HTTP.

    Routes to the appropriate handler based on config.mas_framework:
    - "generic": simple POST/response
    - "neuro_san": streaming_chat with sly_data
    """

    def __init__(
        self,
        transport_config: MASTransportConfig,
        session_id: str = "",
        company_id: int = 0,
    ) -> None:
        self._config = transport_config
        self._session_id = session_id
        self._company_id = company_id
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
        mas_framework = self._config.mas_framework.lower()
        if mas_framework == "neuro_san":
            return await self._decide_neuro_san(
                observation, instructions, observation_tools, message_logger,
            )
        return await self._decide_generic(
            observation, instructions, observation_tools, message_logger,
        )

    async def _decide_neuro_san(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None,
        message_logger: MessageLogger | None,
    ) -> str:
        """Speak neuro-san's streaming_chat protocol.

        POST /api/v1/{agent_name}/streaming_chat
        Request:  {user_message: {type: "HUMAN", text: ...}, sly_data: {observation: ...}}
        Response: newline-delimited JSON, final AGENT_FRAMEWORK message has the answer.
        """
        client = self._get_client()
        endpoint = self._config.endpoint
        if not endpoint:
            raise RuntimeError("MAS HTTP adapter: endpoint URL not configured")

        user_text = instructions
        sly_data: dict[str, Any] = {
            "observation": observation,
            "session_id": self._session_id,
            "company_id": self._company_id,
        }
        if observation_tools:
            sly_data["tools"] = observation_tools

        payload = {
            "user_message": {
                "type": "HUMAN",
                "text": user_text,
            },
            "sly_data": sly_data,
            "chat_filter": {"chat_filter_type": "MAXIMAL"},
            "user_id": os.environ.get("USER", "nttd"),
        }

        if message_logger:
            message_logger("SYSTEM (neuro-san)", f"endpoint: {endpoint} | user_id: {payload.get('user_id')}")
            message_logger("USER", user_text[:500])
            message_logger("SLY_DATA keys", str(list(sly_data.keys())))

        last_error: Exception | None = None
        for attempt in range(self._config.retry_count + 1):
            try:
                return await self._stream_neuro_san(client, endpoint, payload, message_logger)
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < self._config.retry_count:
                    import asyncio
                    wait = self._config.retry_backoff * (2 ** attempt)
                    logger.warning(
                        "Neuro-SAN attempt %d failed (%s), retrying in %.1fs",
                        attempt + 1, exc, wait,
                    )
                    await asyncio.sleep(wait)

        logger.error("Neuro-SAN all %d attempts failed", self._config.retry_count + 1)
        if message_logger:
            message_logger("ERROR", str(last_error))
        return "[]"

    async def _stream_neuro_san(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        payload: dict[str, Any],
        message_logger: MessageLogger | None,
    ) -> str:
        """Send streaming_chat request and collect the final answer."""
        final_text = "[]"
        processor = BasicMessageProcessor()

        async with client.stream(
            "POST", endpoint, json=payload,
            timeout=httpx.Timeout(self._config.timeout, connect=10.0),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Neuro-SAN non-JSON line: %s", line[:200])
                    continue

                resp = msg.get("response", {})
                msg_type = resp.get("type", "")
                text = resp.get("text", "")
                origin = resp.get("origin", [])
                origin_str = origin[0].get("tool", "") if origin else ""

                logger.info(
                    "Neuro-SAN msg: type=%s origin=%s has_structure=%s",
                    msg_type, origin_str, bool(resp.get("structure")),
                )

                processor.process_message(resp)

                if msg_type == "AGENT_FRAMEWORK":
                    if message_logger:
                        summary: dict[str, Any] = {"type": msg_type}
                        if resp.get("structure"):
                            summary["structure"] = resp["structure"]
                        resp_sly_data = resp.get("sly_data")
                        if isinstance(resp_sly_data, dict):
                            summary["sly_data_keys"] = list(resp_sly_data.keys())
                        message_logger("AGENT_FRAMEWORK", json.dumps(summary, indent=2))

                    resp_sly_data = resp.get("sly_data", {})
                    if isinstance(resp_sly_data, dict):
                        action_list = resp_sly_data.get("action_list")
                        if isinstance(action_list, list) and action_list:
                            final_text = json.dumps(action_list)
                            continue
                    if text:
                        final_text = text
                elif text and msg_type != "AGENT":
                    prefix = f"[{origin_str}] " if origin_str else ""
                    logger.info("Neuro-SAN %s%s: %s", prefix, msg_type, text[:500])
                    if message_logger:
                        message_logger(f"{prefix}{msg_type}", text[:2000])

        token_accounting = processor.get_token_accounting()
        if token_accounting:
            self.last_token_usage = _parse_token_structure(token_accounting)
            if message_logger and self.last_token_usage:
                message_logger("TOKEN_ACCOUNTING", json.dumps(token_accounting))
        else:
            self.last_token_usage = None

        logger.info("Neuro-SAN final response (%d chars)", len(final_text))
        if message_logger:
            try:
                parsed_resp = json.loads(final_text)
                if isinstance(parsed_resp, list):
                    display = json.dumps(parsed_resp, indent=2)[:4000]
                else:
                    display = final_text[:2000]
            except (json.JSONDecodeError, TypeError):
                display = final_text[:2000]
            message_logger("FINAL RESPONSE", display)

        return final_text

    async def _decide_generic(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None,
        message_logger: MessageLogger | None,
    ) -> str:
        """Generic HTTP protocol: POST {observation, instructions} -> {actions}."""
        client = self._get_client()

        payload: dict[str, Any] = {
            "observation": observation,
            "instructions": instructions,
            "session_id": self._session_id,
            "company_id": self._company_id,
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

        if self._config.stream_endpoint and message_logger:
            await self._stream_log(payload, message_logger)

        return output

    async def _stream_log(
        self,
        payload: dict[str, Any],
        message_logger: MessageLogger,
    ) -> None:
        """Connect to SSE stream endpoint and log intermediate agent messages."""
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
