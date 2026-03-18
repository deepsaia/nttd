"""LangChain ReAct agent for nttd — reference implementation.

The agent is triggered by the heartbeat compact snapshot.  It uses NttdTools
(agent-side) to query any additional state it needs, then produces a JSON
action list.

Two decide() implementations are shown:
  - Simple: one LLM call with compact snapshot  (fast, good for most cases)
  - ReAct:  multi-turn tool-calling loop before committing to actions

Usage:
    OPENAI_API_KEY=sk-... uv run python agents/langchain_agent.py \\
        --company-id 0 --agent-id langchain_1 [--model gpt-4o-mini] [--react]
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

_SIMPLE_PROMPT = """\
You are an OpenTTD transport company manager (company {company_id}).
Goal: maximize profit by building infrastructure and running vehicle routes.

Current compact game state:
{compact}

Income trend (last {n} snapshots): {income_trend}

Available GS actions you can submit:
  build_road_stop, build_road_depot, buy_vehicle, add_order, start_vehicle,
  stop_vehicle, send_to_depot, build_bridge, found_town, set_loan, ...

Respond with a JSON list of actions:
  [{{"action": "<gs_action>", "params": {{...}}}}]
Return [] if no action is warranted this heartbeat.
"""

_REACT_SYSTEM = """\
You are an OpenTTD transport company manager (company {company_id}).
You have tools to query the current game state.  Use them to gather the
information you need, then output a JSON action list as your Final Answer.

Final Answer format (required):
  FINAL_ACTIONS: [{{"action": "<gs_action>", "params": {{...}}}}]
"""


class LangChainNttdAgent(AgentBase):
    """LangChain agent.  Each heartbeat beat = one LLM decision cycle.

    Tools are defined in this class using NttdTools.as_langchain_tools().
    nttd only sees the compact snapshot trigger and the final action list.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        company_id: int = 0,
        agent_id: str | None = None,
        model: str = "gpt-4o-mini",
        use_react: bool = False,
    ) -> None:
        super().__init__(base_url=base_url, company_id=company_id, agent_id=agent_id)
        self.model = model
        self.use_react = use_react
        self._tools: NttdTools | None = None
        self._llm: Any = None

    def _get_tools(self) -> NttdTools:
        if self._tools is None:
            self._tools = make_tools(self.client, self.company_id)
        return self._tools

    def _get_llm(self, temperature: float = 0.2) -> Any:
        if self._llm is None:
            from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]
            self._llm = ChatOpenAI(model=self.model, temperature=temperature)
        return self._llm

    # ------------------------------------------------------------------
    # Simple mode: one LLM call — compact snapshot → action JSON
    # ------------------------------------------------------------------

    def _decide_simple(self, context: AgentContext) -> list[GameAction]:
        from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore[import-untyped]

        income_trend = [
            snap.get("companies", [{}])[0].get("income", 0)
            for snap in context.history
            if snap.get("companies")
        ]
        prompt = _SIMPLE_PROMPT.format(
            company_id=context.company_id,
            compact=json.dumps(context.compact, indent=2),
            n=len(context.history),
            income_trend=income_trend,
        )
        llm = self._get_llm()
        response = llm.invoke([
            SystemMessage(content="You are a helpful OpenTTD AI transport manager."),
            HumanMessage(content=prompt),
        ])
        return _parse_action_json(response.content)

    # ------------------------------------------------------------------
    # ReAct mode: tool-calling loop → compact + query results → action JSON
    # ------------------------------------------------------------------

    def _decide_react(self, context: AgentContext) -> list[GameAction]:
        from langchain.agents import AgentExecutor, create_react_agent  # type: ignore[import-untyped]
        from langchain.prompts import PromptTemplate  # type: ignore[import-untyped]

        lc_tools = self._get_tools().as_langchain_tools()
        tool_names = ", ".join(t.name for t in lc_tools)
        tool_descs = "\n".join(f"  {t.name}: {t.description}" for t in lc_tools)

        react_prompt = PromptTemplate.from_template(
            _REACT_SYSTEM.format(company_id=context.company_id)
            + f"""
Tools available:
{tool_descs}

Use this format:
  Thought: <your reasoning>
  Action: <tool_name>
  Action Input: <json input or "none">
  Observation: <tool result>
  ... (repeat as needed)
  Thought: I have enough information.
  Final Answer: FINAL_ACTIONS: [...]

Begin.

Compact snapshot (already available):
{json.dumps(context.compact, indent=2)}

Question: What actions should I take this heartbeat?

{{agent_scratchpad}}
"""
        )

        llm = self._get_llm(temperature=0.2)
        agent = create_react_agent(llm, lc_tools, react_prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=lc_tools,
            verbose=True,
            max_iterations=5,
            handle_parsing_errors=True,
        )
        result = executor.invoke({"input": "", "tool_names": tool_names})
        output = result.get("output", "")

        # Extract FINAL_ACTIONS: [...] from the output
        if "FINAL_ACTIONS:" in output:
            raw = output.split("FINAL_ACTIONS:", 1)[1].strip()
            return _parse_action_json(raw)
        return _parse_action_json(output)

    # ------------------------------------------------------------------
    # AgentBase contract
    # ------------------------------------------------------------------

    def decide(self, context: AgentContext) -> list[GameAction]:
        if self.use_react:
            return self._decide_react(context)
        return self._decide_simple(context)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _parse_action_json(raw: str) -> list[GameAction]:
    """Extract a JSON action list from an LLM response string."""
    raw = raw.strip()
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
    parser.add_argument("--react", action="store_true", help="Use ReAct tool-calling mode")
    args = parser.parse_args()

    agent = LangChainNttdAgent(
        base_url=args.base_url,
        company_id=args.company_id,
        agent_id=args.agent_id,
        model=args.model,
        use_react=args.react,
    )
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
