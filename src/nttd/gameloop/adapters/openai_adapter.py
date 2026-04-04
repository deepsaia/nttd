"""OpenAI SDK adapter — multi-turn tool calling with conversation memory."""

from __future__ import annotations

import collections
import json
import logging
import os
from typing import Any

from nttd.gameloop.adapters.base import BaseAdapter, ToolExecutor

logger = logging.getLogger(__name__)

_MAX_HISTORY_CYCLES = 10


class OpenAIAdapter(BaseAdapter):
    """Adapter that uses the OpenAI Python SDK for LLM calls.

    Supports multi-turn tool calling and conversation memory,
    matching the LangChain adapter's capabilities.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key_env: str = "OPENAI_API_KEY",
        max_tool_rounds: int = 8,
        max_history_cycles: int = _MAX_HISTORY_CYCLES,
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._max_tool_rounds = max_tool_rounds
        self._client: Any = None
        self._history: collections.deque[dict[str, str]] = collections.deque(
            maxlen=max_history_cycles * 2,
        )

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "OpenAI SDK not installed. Install with: pip install openai"
                ) from exc

            api_key = os.environ.get(self._api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"Environment variable {self._api_key_env} not set"
                )
            self._client = AsyncOpenAI(api_key=api_key)
        return self._client

    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> str:
        client = self._get_client()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": instructions},
        ]

        # Add conversation history
        for entry in self._history:
            messages.append({"role": entry["role"], "content": entry["content"]})

        # Current observation
        obs_text = (
            f"Current game state:\n{json.dumps(observation, indent=2)}\n\n"
            "Analyze the state. Use observation tools to gather any info you need. "
            "Then output your final action list as a JSON array."
        )
        messages.append({"role": "user", "content": obs_text})

        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if observation_tools:
            kwargs["tools"] = observation_tools
            kwargs["tool_choice"] = "auto"

        msg = None
        for round_num in range(self._max_tool_rounds):
            response = await client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            messages.append(msg.model_dump())

            if not msg.tool_calls:
                final_content = msg.content or "[]"
                self._record_history(obs_text, final_content)
                return final_content

            # Execute tool calls
            if tool_executor is None:
                logger.warning("LLM requested tools but no executor provided")
                final_content = msg.content or "[]"
                self._record_history(obs_text, final_content)
                return final_content

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}
                logger.info(
                    "Agent tool call [round %d]: %s(%s)",
                    round_num + 1, tool_name, json.dumps(tool_args),
                )
                result = await tool_executor(tool_name, tool_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            kwargs["messages"] = messages

        logger.warning("Max tool rounds (%d) exceeded", self._max_tool_rounds)
        final_content = msg.content or "[]" if msg else "[]"
        self._record_history(obs_text, final_content)
        return final_content

    def _record_history(self, user_content: str, assistant_content: str) -> None:
        """Record one cycle's exchange into conversation memory."""
        self._history.append({"role": "user", "content": user_content})
        self._history.append({"role": "assistant", "content": assistant_content})

    async def close(self) -> None:
        self._history.clear()
        if self._client is not None:
            await self._client.close()
            self._client = None
