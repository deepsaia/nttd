"""LangChain ReAct agent for nttd — reference implementation.

One LLM call per heartbeat beat. Tools query and build infrastructure.
Usage:
    OPENAI_API_KEY=sk-... uv run python agents/langchain_agent.py \\
        --company-id 0 --agent-id langchain_1 [--model gpt-4o-mini]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from agents.base import AgentBase, AgentContext, GameAction

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an OpenTTD transport company manager (company {company_id}).
Your goal: maximize profit by building infrastructure and running vehicle routes.

Current game state (compact):
{compact}

History (last {history_len} snapshots income): {income_trend}

Respond with a JSON list of actions, each: {{"action": "<gs_action>", "params": {{...}}}}
Return [] if no action is warranted. Keep actions within your company scope.
"""


class LangChainNttdAgent(AgentBase):
    """LangChain ReAct agent. One LLM call per heartbeat beat."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        company_id: int = 0,
        agent_id: str | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        super().__init__(base_url=base_url, company_id=company_id, agent_id=agent_id)
        self.model = model
        self._llm: Any = None

    def _get_llm(self) -> Any:
        if self._llm is None:
            from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
            self._llm = ChatOpenAI(model=self.model, temperature=0.2)
        return self._llm

    def decide(self, context: AgentContext) -> list[GameAction]:
        from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore[import-untyped]

        income_trend = [
            snap.get("companies", [{}])[0].get("income", 0)
            for snap in context.history
            if snap.get("companies")
        ]

        prompt = _SYSTEM_PROMPT.format(
            company_id=context.company_id,
            compact=json.dumps(context.compact, indent=2),
            history_len=len(context.history),
            income_trend=income_trend,
        )

        llm = self._get_llm()
        response = llm.invoke([
            SystemMessage(content="You are a helpful OpenTTD AI transport manager."),
            HumanMessage(content=prompt),
        ])

        raw = response.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        try:
            action_list = json.loads(raw)
            return [
                GameAction(action=a["action"], params=a.get("params", {}))
                for a in action_list
                if isinstance(a, dict) and "action" in a
            ]
        except (json.JSONDecodeError, KeyError):
            logger.warning("LLM returned unparseable response: %s", raw[:200])
            return []


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="LangChain nttd agent")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()

    agent = LangChainNttdAgent(
        base_url=args.base_url,
        company_id=args.company_id,
        agent_id=args.agent_id,
        model=args.model,
    )
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
