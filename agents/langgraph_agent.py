"""LangGraph Planner+Executor agent for nttd — reference implementation.

Planner fires every N heartbeat beats to set strategic goals.
Executor runs every beat and produces 1-3 GS actions per goal.
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

logger = logging.getLogger(__name__)

_PLANNER_PROMPT = """You are a strategic OpenTTD transport planner for company {company_id}.
Given the last {n} game snapshots, produce 1-3 high-level strategic goals.
Respond with a JSON list of goal strings. E.g. ["Build bus route in Townington", "Buy 2 more trains"]

Recent snapshots (compact):
{snapshots}
"""

_EXECUTOR_PROMPT = """You are an OpenTTD action executor for company {company_id}.
Current goal: {goal}

Current state (compact):
{compact}

Produce 1-3 GS API actions to progress toward this goal.
Respond with a JSON list: [{{"action": "<gs_action>", "params": {{...}}}}]
"""


class LangGraphNttdAgent(AgentBase):
    """Planner+Executor graph. Replans every N heartbeat beats."""

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
        self._llm: Any = None

    def _get_llm(self, temperature: float = 0.3) -> Any:
        from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
        return ChatOpenAI(model=self.model, temperature=temperature)

    def _run_planner(self, context: AgentContext) -> None:
        from langchain_core.messages import HumanMessage  # type: ignore[import-untyped]

        snapshots_text = json.dumps(
            [s for s in context.history[-2:]] if context.history else [context.compact],
            indent=2,
        )
        prompt = _PLANNER_PROMPT.format(
            company_id=context.company_id,
            n=len(context.history),
            snapshots=snapshots_text,
        )
        llm = self._get_llm(temperature=0.7)
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            self._goals = json.loads(raw)
            self._goal_index = 0
            logger.info("Planner set goals: %s", self._goals)
        except json.JSONDecodeError:
            logger.warning("Planner returned unparseable goals: %s", raw[:200])

    def _run_executor(self, context: AgentContext) -> list[GameAction]:
        from langchain_core.messages import HumanMessage  # type: ignore[import-untyped]

        if not self._goals:
            return []

        goal = self._goals[self._goal_index % len(self._goals)]
        prompt = _EXECUTOR_PROMPT.format(
            company_id=context.company_id,
            goal=goal,
            compact=json.dumps(context.compact, indent=2),
        )
        llm = self._get_llm(temperature=0.2)
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            action_list = json.loads(raw)
            # Advance to next goal after executor runs
            self._goal_index += 1
            return [
                GameAction(action=a["action"], params=a.get("params", {}))
                for a in action_list
                if isinstance(a, dict) and "action" in a
            ]
        except (json.JSONDecodeError, KeyError):
            logger.warning("Executor returned unparseable actions: %s", raw[:200])
            return []

    def decide(self, context: AgentContext) -> list[GameAction]:
        needs_plan = (
            not self._goals
            or context.heartbeat_count % self.planner_interval == 0
        )
        if needs_plan:
            self._run_planner(context)
        return self._run_executor(context)


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
