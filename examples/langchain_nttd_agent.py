#!/usr/bin/env python3
"""LangChain agent for nttd — observes game state, decides actions, executes via interpreter.

The agent uses MCP observation tools to understand the game world and outputs
a structured action list. The interpreter endpoint handles execution.

Usage:
    OPENAI_API_KEY=sk-... uv run python examples/langchain_nttd_agent.py \
        --session-id ses_abc123 --company-id 0 --model gpt-4o

Requirements:
    uv sync --extra agents
"""

import argparse
import asyncio
import json
import logging

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from examples.agent_instructions import get_bus_agent_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("langchain_nttd")


# ── Observation tools (LangChain @tool wrappers over nttd REST) ────────

def create_observation_tools(http: httpx.AsyncClient, session_url: str, company_id: int) -> list:
    """Create LangChain tools that query nttd's observation endpoints."""

    @tool
    async def get_state_compact() -> str:
        """Get a compact summary of the game: finances, vehicles, stations, towns."""
        resp = await http.get(f"{session_url}/state/compact", params={"company_id": company_id})
        return resp.text

    @tool
    async def get_towns() -> str:
        """List all towns on the map with name, population, and coordinates."""
        resp = await http.post(f"{session_url}/state/gs/query", params={"action": "get_towns"}, json={})
        return json.dumps(resp.json().get("result", []))

    @tool
    async def get_engines(vehicle_type: int = 1) -> str:
        """List purchasable engines. vehicle_type: 0=train, 1=road, 2=ship, 3=air."""
        resp = await http.post(
            f"{session_url}/state/gs/query",
            params={"action": "get_engines"},
            json={"company_id": company_id, "vehicle_type": vehicle_type},
        )
        return json.dumps(resp.json().get("result", []))

    @tool
    async def get_vehicles() -> str:
        """List your vehicles with id, type, name, and profit."""
        resp = await http.post(
            f"{session_url}/state/gs/query",
            params={"action": "get_vehicles"},
            json={"company_id": company_id},
        )
        return json.dumps(resp.json().get("result", []))

    @tool
    async def get_company_finance() -> str:
        """Get detailed financials: balance, loan, income, expenses."""
        resp = await http.post(
            f"{session_url}/state/gs/query",
            params={"action": "get_company_finance"},
            json={"company_id": company_id},
        )
        return json.dumps(resp.json().get("result", {}))

    @tool
    async def find_bus_stop_spots(town_id: int, max_results: int = 5) -> str:
        """Find road tiles near a town suitable for building bus stops."""
        resp = await http.post(
            f"{session_url}/state/gs/query",
            params={"action": "find_bus_stop_spots"},
            json={"town_id": town_id, "company_id": company_id, "max_results": max_results},
        )
        return json.dumps(resp.json().get("result", []))

    @tool
    async def find_depot_spots(town_id: int, max_results: int = 5) -> str:
        """Find road tiles near a town suitable for building a road depot."""
        resp = await http.post(
            f"{session_url}/state/gs/query",
            params={"action": "find_depot_spots"},
            json={"town_id": town_id, "company_id": company_id, "max_results": max_results},
        )
        return json.dumps(resp.json().get("result", []))

    @tool
    async def validate_actions(actions: list[dict]) -> str:
        """Validate a proposed action list without executing. Returns valid/invalid per action."""
        resp = await http.post(
            f"{session_url}/actions/interpret/validate",
            json=actions,
        )
        return resp.text

    return [
        get_state_compact, get_towns, get_engines, get_vehicles,
        get_company_finance, find_bus_stop_spots, find_depot_spots,
        validate_actions,
    ]


# ── Interpreter — sends action list for execution ─────────────────────

async def interpret_actions(
    http: httpx.AsyncClient, session_url: str, actions: list[dict], company_id: int,
) -> list[dict]:
    """Submit agent's action list to nttd interpreter for execution."""
    resp = await http.post(
        f"{session_url}/actions/interpret",
        json=actions,
        params={"company_id": company_id},
    )
    resp.raise_for_status()
    return resp.json()


# ── Agent loop: observe → decide (LLM) → interpret → execute ──────────

async def run_agent(
    base_url: str,
    session_id: str,
    company_id: int,
    model: str,
    poll_interval: float,
    use_tools: bool,
) -> None:
    session_url = f"{base_url}/sessions/{session_id}"
    system_prompt = get_bus_agent_prompt(company_id)

    llm = ChatOpenAI(model=model, temperature=0.2)

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        # Register as agent
        await http.post(f"{session_url}/agents/connect", json={
            "agent_id": f"langchain_{model}", "name": f"LangChain {model}", "company_scope": [company_id],
        })
        logger.info("Connected to session %s as company %d", session_id, company_id)

        observation_tools = create_observation_tools(http, session_url, company_id)

        if use_tools:
            # Tool-calling mode: LLM can call observation tools, then output actions
            llm_with_tools = llm.bind_tools(observation_tools)

        cycle = 0
        history: list[str] = []

        while True:
            # ── Observe ──
            resp = await http.get(f"{session_url}/state/compact", params={"company_id": company_id})
            compact = resp.json()
            compact_str = json.dumps(compact, indent=2)
            history.append(compact_str)
            if len(history) > 5:
                history.pop(0)

            logger.info("Cycle %d | date=%s | vehicles=%s",
                        cycle, compact.get("game_date", "?"),
                        compact.get("vehicles", {}).get("total", 0))

            # ── Decide (LLM call) ──
            user_message = (
                f"Current game state:\n{compact_str}\n\n"
                f"Cycle: {cycle}\n"
                f"Recent income trend: {[(json.loads(h).get('company') or {}).get('income', 0) for h in history]}\n\n"
                "Analyze the game state and decide what actions to take. "
                "Use observation tools if you need more detail about specific towns, "
                "engines, or tile locations. Then output your action list."
            )

            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]

            if use_tools:
                # Multi-turn tool calling — LLM can query observations, then produce actions
                for _ in range(5):  # max tool-calling rounds
                    response = await llm_with_tools.ainvoke(messages)
                    messages.append(response)

                    if not response.tool_calls:
                        break

                    for tc in response.tool_calls:
                        tool_fn = next((t for t in observation_tools if t.name == tc["name"]), None)
                        if tool_fn:
                            result = await tool_fn.ainvoke(tc["args"])
                            from langchain_core.messages import ToolMessage
                            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

                raw_output = response.content
            else:
                # Simple mode — one LLM call with compact state
                response = await llm.ainvoke(messages)
                raw_output = response.content

            # ── Parse action list from LLM output ──
            actions = _parse_actions(raw_output)
            logger.info("LLM proposed %d action(s)", len(actions))

            # ── Interpret & Execute ──
            if actions:
                results = await interpret_actions(http, session_url, actions, company_id)
                for r in results:
                    status = r.get("status", "?")
                    logger.info("  %s: %s %s", r.get("action_id", "?"), status, r.get("error", ""))

            cycle += 1
            await asyncio.sleep(poll_interval)


def _parse_actions(raw: str) -> list[dict]:
    """Extract JSON action array from LLM response text."""
    import re
    raw = raw.strip()

    # Try direct parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding any JSON array
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse actions from LLM output: %.200s", raw)
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangChain nttd agent")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--tools", action="store_true", help="Enable tool-calling mode (multi-turn)")
    args = parser.parse_args()

    asyncio.run(run_agent(
        base_url=args.base_url,
        session_id=args.session_id,
        company_id=args.company_id,
        model=args.model,
        poll_interval=args.poll_interval,
        use_tools=args.tools,
    ))
