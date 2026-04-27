"""OpenAI SDK adapter — multi-turn tool calling (stateless).

Memory is handled externally: connection.py injects a rolling action_history
into the observation so the agent knows what it successfully built in prior
cycles. The adapter itself is stateless -- no conversation history.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from nttd.gameloop.adapters.base import BaseAdapter, MessageLogger, ToolExecutor
from nttd.gameloop.schemas import TokenUsage
from nttd.gameloop.token_costs import estimate_cost

logger = logging.getLogger(__name__)


class OpenAIAdapter(BaseAdapter):
    """Adapter that uses the OpenAI Python SDK for LLM calls.

    Supports multi-turn tool calling within a single cycle.
    Stateless: no conversation history across cycles.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key_env: str = "OPENAI_API_KEY",
        max_tool_rounds: int = 8,
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._max_tool_rounds = max_tool_rounds
        self._client: Any = None

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
        message_logger: MessageLogger | None = None,
    ) -> str:
        client = self._get_client()

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": instructions},
        ]
        if message_logger:
            message_logger("SYSTEM", instructions)

        # Current observation (includes action_history from prior cycles)
        obs_text = (
            f"Current game state:\n{json.dumps(observation, indent=2)}\n\n"
            "Analyze the state. Use observation tools to gather any info you need. "
            "Then output your final action list as a JSON array."
        )
        messages.append({"role": "user", "content": obs_text})
        if message_logger:
            message_logger("USER", obs_text)

        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if observation_tools:
            kwargs["tools"] = observation_tools
            kwargs["tool_choice"] = "auto"

        total_prompt = 0
        total_completion = 0

        def _record_usage() -> None:
            self.last_token_usage = TokenUsage(
                prompt_tokens=total_prompt,
                completion_tokens=total_completion,
                total_tokens=total_prompt + total_completion,
                total_cost=estimate_cost(self._model, total_prompt, total_completion),
                model=self._model,
                provider="openai",
            )

        msg = None
        for round_num in range(self._max_tool_rounds):
            response = await client.chat.completions.create(**kwargs)
            if response.usage:
                total_prompt += response.usage.prompt_tokens or 0
                total_completion += response.usage.completion_tokens or 0
            msg = response.choices[0].message
            messages.append(msg.model_dump())

            if not msg.tool_calls:
                output = msg.content or "[]"
                if message_logger:
                    message_logger("ASSISTANT", output)
                _record_usage()
                return output

            # Execute tool calls
            if tool_executor is None:
                logger.warning("LLM requested tools but no executor provided")
                output = msg.content or "[]"
                if message_logger:
                    message_logger("ASSISTANT", output)
                _record_usage()
                return output

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
                if message_logger:
                    message_logger(f"TOOL CALL (round {round_num + 1})", f"{tool_name}({json.dumps(tool_args)})")
                result = await tool_executor(tool_name, tool_args)
                if message_logger:
                    message_logger("TOOL RESULT", result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            kwargs["messages"] = messages

        logger.warning("Max tool rounds (%d) exceeded", self._max_tool_rounds)
        output = msg.content or "[]" if msg else "[]"
        if message_logger:
            message_logger("ASSISTANT", output)
        _record_usage()
        return output

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
