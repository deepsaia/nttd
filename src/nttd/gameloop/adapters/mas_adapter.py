"""Multi-Agent System (MAS) adapter.

Implements the BaseAdapter interface by orchestrating a graph of sub-agents.
Each sub-agent has its own prompt, model, and tool set. Sub-agents can appear
as tools in other agents' tool lists, enabling hierarchical/DAG topologies.

The graph definition is loaded from a HOCON .conf file (mas_config path).
The runtime backend is pluggable: "custom" uses built-in LLM callers,
while "langgraph", "crewai", etc. delegate to their respective frameworks.

This adapter is transparent to the connection layer -- it accepts the same
decide() call and returns a JSON action list.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from nttd.gameloop.adapters.base import BaseAdapter, MessageLogger, ToolExecutor

logger = logging.getLogger(__name__)


class SubAgentNode:
    """A single agent node in the MAS graph."""

    def __init__(
        self,
        agent_id: str,
        role: str,
        prompt: str,
        model: str,
        tools: list[str],
        output_schema: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.prompt = prompt
        self.model = model
        self.tools = tools
        self.output_schema = output_schema


class MASConfig:
    """Parsed MAS graph configuration."""

    def __init__(self, config_path: str) -> None:
        from pyhocon import ConfigFactory

        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"MAS config not found: {config_path}")

        conf = ConfigFactory.parse_file(str(path))
        mas = conf.get("mas", conf)

        self.runtime: str = mas.get_string("runtime", "custom")
        self.entry_agent: str = mas.get_string("entry_agent")

        self.agents: dict[str, SubAgentNode] = {}
        for agent_conf in mas.get_list("agents"):
            node = SubAgentNode(
                agent_id=agent_conf.get_string("id"),
                role=agent_conf.get_string("role", ""),
                prompt=agent_conf.get_string("prompt", ""),
                model=agent_conf.get_string("model", ""),
                tools=agent_conf.get_list("tools", []),
                output_schema=agent_conf.get_string("output_schema", ""),
            )
            self.agents[node.agent_id] = node

        if self.entry_agent not in self.agents:
            raise ValueError(
                f"entry_agent '{self.entry_agent}' not found in agents list"
            )


class MASAdapter(BaseAdapter):
    """Multi-agent system adapter that orchestrates sub-agents as a graph.

    Sub-agents appear as tools to their parent agents. When a parent "calls"
    a sub-agent tool, the sub-agent runs its own LLM call with its own prompt
    and tools, then returns its output as the tool result.

    Supports any topology: linear chains, DAGs, or recursive hierarchies.
    """

    def __init__(
        self,
        mas_config_path: str,
        default_model: str = "gpt-4o",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self._config = MASConfig(mas_config_path)
        self._default_model = default_model
        self._api_key_env = api_key_env
        self._llm_cache: dict[str, Any] = {}

    def _get_llm(self, model: str) -> Any:
        """Get or create a LangChain chat model for the given model name."""
        if model in self._llm_cache:
            return self._llm_cache[model]

        import importlib

        from nttd.gameloop.adapters.langchain_adapter import _resolve_provider

        package_name, class_name, default_env = _resolve_provider(model)
        api_key_env = self._api_key_env or default_env
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Environment variable {api_key_env} not set")

        module = importlib.import_module(package_name)
        chat_class = getattr(module, class_name)
        llm = chat_class(model=model, api_key=api_key, temperature=0.2)
        self._llm_cache[model] = llm
        return llm

    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        message_logger: MessageLogger | None = None,
    ) -> str:
        runtime = self._config.runtime
        if runtime == "custom":
            return await self._run_custom(
                observation, instructions, observation_tools, tool_executor, message_logger,
            )
        raise NotImplementedError(
            f"MAS runtime '{runtime}' not yet implemented. "
            f"Available: custom. Coming soon: langgraph, crewai, pydanticai, agno, autogen, neuro-san"
        )

    async def _run_custom(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
        message_logger: MessageLogger | None = None,
    ) -> str:
        """Run the MAS graph using built-in LLM callers with sub-agents-as-tools."""
        entry = self._config.entry_agent
        result = await self._invoke_agent(
            entry, observation, instructions, observation_tools, tool_executor, message_logger,
        )
        return result

    async def _invoke_agent(
        self,
        agent_id: str,
        observation: dict[str, Any],
        parent_instructions: str,
        all_observation_tools: list[dict[str, Any]] | None,
        tool_executor: ToolExecutor | None,
        message_logger: MessageLogger | None,
    ) -> str:
        """Invoke a single sub-agent node, resolving its tools (including sub-agent tools)."""
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        node = self._config.agents[agent_id]
        model = node.model or self._default_model
        llm = self._get_llm(model)

        # Build this agent's tool list: filter observation tools + add sub-agent tools
        agent_tools = self._build_tool_schemas(node, all_observation_tools)

        if agent_tools:
            bound_llm = llm.bind_tools(agent_tools)
        else:
            bound_llm = llm

        # Build system prompt for this sub-agent
        system_prompt = node.prompt or parent_instructions
        if node.role:
            system_prompt = f"ROLE: {node.role}\n\n{system_prompt}"
        if node.output_schema:
            system_prompt += f"\n\nOUTPUT FORMAT: {node.output_schema}"

        messages: list[Any] = [SystemMessage(content=system_prompt)]
        if message_logger:
            message_logger(f"[{agent_id}] SYSTEM", system_prompt)

        # User message: current observation state
        obs_text = json.dumps(observation, indent=2)
        messages.append(HumanMessage(content=obs_text))
        if message_logger:
            message_logger(f"[{agent_id}] USER", obs_text)

        # Multi-turn tool calling loop
        max_rounds = 8
        for round_num in range(max_rounds):
            response = await bound_llm.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                output = response.content or "[]"
                if message_logger:
                    message_logger(f"[{agent_id}] ASSISTANT", output)
                return output

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                if message_logger:
                    message_logger(
                        f"[{agent_id}] TOOL CALL (round {round_num + 1})",
                        f"{tool_name}({json.dumps(tool_args)})",
                    )

                # Check if tool_name is a sub-agent
                if tool_name in self._config.agents:
                    sub_obs = {**observation}
                    if tool_args:
                        sub_obs["parent_request"] = tool_args
                    result = await self._invoke_agent(
                        tool_name, sub_obs, parent_instructions,
                        all_observation_tools, tool_executor, message_logger,
                    )
                elif tool_executor:
                    result = await tool_executor(tool_name, tool_args)
                else:
                    result = json.dumps({"error": f"No executor for tool: {tool_name}"})

                if message_logger:
                    message_logger(f"[{agent_id}] TOOL RESULT", result)

                messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

        logger.warning("MAS agent %s exceeded max tool rounds", agent_id)
        output = response.content or "[]" if response else "[]"
        if message_logger:
            message_logger(f"[{agent_id}] ASSISTANT", output)
        return output

    def _build_tool_schemas(
        self,
        node: SubAgentNode,
        all_observation_tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Build the tool schema list for a sub-agent node.

        Includes:
        - Observation tools that match the node's tool list
        - Sub-agent tools (other agents referenced by ID in the tools list)
        """
        schemas: list[dict[str, Any]] = []
        obs_tool_map: dict[str, dict[str, Any]] = {}
        if all_observation_tools:
            for t in all_observation_tools:
                obs_tool_map[t["function"]["name"]] = t

        for tool_name in node.tools:
            if tool_name in obs_tool_map:
                schemas.append(obs_tool_map[tool_name])
            elif tool_name in self._config.agents:
                sub_node = self._config.agents[tool_name]
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": sub_node.role or f"Delegate to {tool_name} sub-agent",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "request": {
                                    "type": "string",
                                    "description": "What you need this agent to do",
                                },
                            },
                            "required": [],
                        },
                    },
                })
            else:
                logger.warning(
                    "MAS agent %s references unknown tool: %s", node.agent_id, tool_name,
                )

        return schemas

    async def close(self) -> None:
        self._llm_cache.clear()
