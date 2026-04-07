"""LangChain adapter — multi-turn tool calling with conversation memory.

Supports multiple LLM providers via LangChain's chat model interface:
- OpenAI: gpt-4o, gpt-5.2, gpt-5.4, etc. (api_key_env=OPENAI_API_KEY)
- Anthropic: claude-sonnet-4-6, claude-haiku-4-5, etc. (api_key_env=ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import collections
import json
import logging
import os
from typing import Any

from nttd.gameloop.adapters.base import BaseAdapter, ToolExecutor

logger = logging.getLogger(__name__)

_MAX_HISTORY_CYCLES = 2

# Model prefix → (package, class name, env var default)
_PROVIDER_MAP: dict[str, tuple[str, str, str]] = {
    "claude": ("langchain_anthropic", "ChatAnthropic", "ANTHROPIC_API_KEY"),
    "gpt": ("langchain_openai", "ChatOpenAI", "OPENAI_API_KEY"),
}


def _resolve_provider(model: str) -> tuple[str, str, str]:
    """Determine LangChain provider class from model name."""
    for prefix, info in _PROVIDER_MAP.items():
        if model.startswith(prefix):
            return info
    # Default to OpenAI for unknown models
    return "langchain_openai", "ChatOpenAI", "OPENAI_API_KEY"


class LangChainAdapter(BaseAdapter):
    """Adapter that uses LangChain's chat model interface with tool calling.

    Supports:
    - Multi-turn tool calling: the LLM can call observation tools to
      gather data before producing its final action list.
    - Conversation memory: retains the last N cycle exchanges so the
      agent can learn from its previous actions and observations.
    - Multiple providers: OpenAI, Anthropic (auto-detected from model name).
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key_env: str = "",
        temperature: float = 0.2,
        max_tool_rounds: int = 8,
        max_history_cycles: int = _MAX_HISTORY_CYCLES,
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._temperature = temperature
        self._max_tool_rounds = max_tool_rounds
        self._max_history_cycles = max_history_cycles
        self._llm: Any = None
        self._history: collections.deque[dict[str, str]] = collections.deque(
            maxlen=max_history_cycles * 2,
        )

    def _get_llm(self) -> Any:
        if self._llm is not None:
            return self._llm

        package_name, class_name, default_env = _resolve_provider(self._model)
        api_key_env = self._api_key_env or default_env

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Environment variable {api_key_env} not set")

        try:
            import importlib
            module = importlib.import_module(package_name)
            chat_class = getattr(module, class_name)
        except ImportError as exc:
            raise RuntimeError(
                f"{package_name} not installed. Install with: pip install {package_name}"
            ) from exc

        self._llm = chat_class(
            model=self._model,
            api_key=api_key,
            temperature=self._temperature,
        )
        logger.info("LangChain adapter initialized: model=%s, provider=%s", self._model, class_name)
        return self._llm

    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> str:
        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        llm = self._get_llm()

        # Bind tools if provided
        if observation_tools:
            bound_llm = llm.bind_tools(observation_tools)
        else:
            bound_llm = llm

        # Build message list: system + history + current observation
        messages: list[Any] = [SystemMessage(content=instructions)]

        # Add conversation history (previous cycles' observations and responses)
        for entry in self._history:
            if entry["role"] == "user":
                messages.append(HumanMessage(content=entry["content"]))
            else:
                messages.append(AIMessage(content=entry["content"]))

        # Current observation
        obs_text = (
            f"Current game state:\n{json.dumps(observation, indent=2)}\n\n"
            "Analyze the state. Use observation tools to gather any info you need "
            "(e.g., find_bus_stop_spots, get_engines). Then output your final "
            "action list as a JSON array."
        )
        messages.append(HumanMessage(content=obs_text))

        # Multi-turn tool calling loop
        response = None
        for round_num in range(self._max_tool_rounds):
            response = await bound_llm.ainvoke(messages)
            messages.append(response)

            # No tool calls → final response
            if not response.tool_calls:
                final_content = response.content or "[]"
                self._record_history(obs_text, final_content)
                return final_content

            # Execute tool calls
            if tool_executor is None:
                logger.warning("LLM requested tools but no executor provided")
                final_content = response.content or "[]"
                self._record_history(obs_text, final_content)
                return final_content

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                logger.info(
                    "Agent tool call [round %d]: %s(%s)",
                    round_num + 1, tool_name, json.dumps(tool_args),
                )
                result = await tool_executor(tool_name, tool_args)
                messages.append(
                    ToolMessage(content=result, tool_call_id=tool_call["id"])
                )

        # Exhausted tool rounds — take whatever we have
        logger.warning("Max tool rounds (%d) exceeded", self._max_tool_rounds)
        final_content = response.content or "[]" if response else "[]"
        self._record_history(obs_text, final_content)
        return final_content

    def _record_history(self, user_content: str, assistant_content: str) -> None:
        """Record one cycle's exchange into conversation memory."""
        self._history.append({"role": "user", "content": user_content})
        self._history.append({"role": "assistant", "content": assistant_content})

    async def close(self) -> None:
        self._history.clear()
        self._llm = None
