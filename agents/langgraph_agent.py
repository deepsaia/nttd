"""LangGraph Planner+Executor agent for nttd — reference implementation.

Planner fires every N heartbeat beats to set strategic goals using NttdTools.
Executor runs every beat, queries current state via tools, and produces actions.

The Planner and Executor are LangGraph graph nodes.  Tools are defined in this
file using NttdTools — they are NOT part of nttd; nttd only sees the compact
snapshot trigger and the final action list.

Usage:
    OPENAI_API_KEY=sk-... uv run python agents/langgraph_agent.py \\
        --company-id 1 --agent-id langgraph_1 [--planner-interval 5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from agents.base import AgentBase, AgentContext, GameAction
from agents.tools import NttdTools, make_tools

logger = logging.getLogger(__name__)

_PLANNER_PROMPT = """\
You are a strategic OpenTTD transport planner for company {company_id}.

Recent state snapshots:
{snapshots}

Available subsidies (high-value opportunities):
{subsidies}

Towns (largest first):
{towns}

Produce 1-3 high-level strategic goals as a JSON list of strings.
Example: ["Build bus route between Townington and Villageville",
          "Buy 2 more road vehicles when funds allow"]
"""

_EXECUTOR_PROMPT = """\
You are an OpenTTD action executor for company {company_id}.
Current goal: {goal}

Current state:
{compact}

Current vehicles: {vehicles}
Current stations: {stations}

Produce 1-3 GS API actions to progress toward this goal.
Respond ONLY with a JSON list:
  [{{"action": "<gs_action>", "params": {{...}}}}]
"""


class LangGraphNttdAgent(AgentBase):
    """Planner+Executor.  Replans every N heartbeat beats using NttdTools."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        company_id: int = 0,
        agent_id: str | None = None,
        model: str = "gpt-4o-mini",
        planner_interval: int = 5,
    ) -> None:
        super().__init__(base_url=base_url, company_id=company_id, agent_id=agent_id)
        self.model = model
        self.planner_interval = planner_interval
        self._goals: list[str] = []
        self._goal_index: int = 0
        self._tools: NttdTools | None = None

    def _get_tools(self) -> NttdTools:
        if self._tools is None:
            self._tools = make_tools(self.client, self.company_id)
        return self._tools

    def _get_llm(self, temperature: float = 0.3) -> Any:
        from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
        return ChatOpenAI(model=self.model, temperature=temperature)

    # ------------------------------------------------------------------
    # Planner node — uses tools to gather strategic context
    # ------------------------------------------------------------------

    def _run_planner(self, context: AgentContext) -> None:
        from langchain_core.messages import HumanMessage  # type: ignore[import-untyped]

        tools = self._get_tools()

        # Query richer context than the compact snapshot provides
        subsidies = tools.get_subsidies()
        towns = tools.get_towns()
        towns_top = sorted(towns, key=lambda t: t.get("population", 0), reverse=True)[:5]

        snapshots_text = json.dumps(
            context.history[-2:] if context.history else [context.compact],
            indent=2,
        )
        prompt = _PLANNER_PROMPT.format(
            company_id=context.company_id,
            snapshots=snapshots_text,
            subsidies=json.dumps(subsidies[:5], indent=2),
            towns=json.dumps(towns_top, indent=2),
        )
        llm = self._get_llm(temperature=0.7)
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = _strip_fences(response.content)
        try:
            self._goals = json.loads(raw)
            self._goal_index = 0
            logger.info("Planner set goals: %s", self._goals)
        except json.JSONDecodeError:
            logger.warning("Planner returned unparseable goals: %s", raw[:200])

    # ------------------------------------------------------------------
    # Executor node — uses tools to query current state, then acts
    # ------------------------------------------------------------------

    def _run_executor(self, context: AgentContext) -> list[GameAction]:
        from langchain_core.messages import HumanMessage  # type: ignore[import-untyped]

        if not self._goals:
            return []

        tools = self._get_tools()
        vehicles = tools.get_vehicles()
        stations = tools.get_stations()

        goal = self._goals[self._goal_index % len(self._goals)]
        prompt = _EXECUTOR_PROMPT.format(
            company_id=context.company_id,
            goal=goal,
            compact=json.dumps(context.compact, indent=2),
            vehicles=json.dumps(vehicles, indent=2),
            stations=json.dumps(stations, indent=2),
        )
        llm = self._get_llm(temperature=0.2)
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = _strip_fences(response.content)
        try:
            action_list = json.loads(raw)
            self._goal_index += 1
            return [
                GameAction(action=a["action"], params=a.get("params", {}))
                for a in action_list
                if isinstance(a, dict) and "action" in a
            ]
        except (json.JSONDecodeError, KeyError):
            logger.warning("Executor returned unparseable actions: %s", raw[:200])
            return []

    # ------------------------------------------------------------------
    # AgentBase contract
    # ------------------------------------------------------------------

    def decide(self, context: AgentContext) -> list[GameAction]:
        needs_plan = (
            not self._goals
            or context.heartbeat_count % self.planner_interval == 0
        )
        if needs_plan:
            self._run_planner(context)
        return self._run_executor(context)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="LangGraph nttd agent")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--company-id", type=int, default=1)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--planner-interval", type=int, default=5)
    args = parser.parse_args()

    agent = LangGraphNttdAgent(
        base_url=args.base_url,
        company_id=args.company_id,
        agent_id=args.agent_id,
        model=args.model,
        planner_interval=args.planner_interval,
    )
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
