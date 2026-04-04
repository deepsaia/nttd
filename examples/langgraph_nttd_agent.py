#!/usr/bin/env python3
"""LangGraph agent for nttd — strategic planner + tactical executor.

Uses a two-node graph:
  - Planner: analyzes game state every N cycles, sets strategic goals
  - Executor: each cycle, picks a goal and outputs tactical actions

The agent uses observation tools for both planning and execution,
and outputs action lists for the interpreter.

Usage:
    OPENAI_API_KEY=sk-... uv run python examples/langgraph_nttd_agent.py \
        --session-id ses_abc123 --company-id 0

Requirements:
    uv sync --extra agents-langgraph
"""

import argparse
import asyncio
import json
import logging

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from examples.agent_instructions import ACTION_FORMAT_INSTRUCTIONS, ACTION_REFERENCE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("langgraph_nttd")


# ── Prompts ────────────────────────────────────────────────────────────

PLANNER_PROMPT = """\
You are a strategic OpenTTD transport planner for company {company_id}.

Your job is to analyze the current game state and produce 1-3 high-level
strategic goals. These goals will be executed one at a time by the executor.

Current game state:
{compact}

Towns (sorted by population):
{towns}

Available subsidies (bonus revenue opportunities):
{subsidies}

Your company's vehicles:
{vehicles}

Your stations:
{stations}

GUIDELINES:
- If no routes exist yet, prioritize "Build a bus route between <Town A> and <Town B>"
  choosing the two largest towns.
- If routes exist but are unprofitable, consider "Clone vehicle on <route>" or
  "Add a truck route between <Industry> and <Town>".
- If profitable, consider expansion: new routes, new transport types.
- Be specific: name towns, industries, or vehicle types in your goals.

Respond with a JSON array of 1-3 goal strings:
["Goal 1", "Goal 2", "Goal 3"]"""

EXECUTOR_PROMPT = """\
You are an OpenTTD action executor for company {company_id}.

CURRENT GOAL: {goal}

Game state:
{compact}

Your vehicles: {vehicles}
Your stations: {stations}

Produce actions to progress toward this goal. If the goal requires
multiple steps (e.g., build stops, buy vehicle, set orders), output
all steps you can take this cycle. If you need information first,
the game state above should have what you need — if not, output []
and the planner will reassess next cycle.

{action_format}

{action_reference}"""


# ── Observation helpers ────────────────────────────────────────────────

async def observe(http: httpx.AsyncClient, session_url: str, company_id: int) -> dict:
    """Gather all observation data needed for planning and execution."""
    compact_resp = await http.get(f"{session_url}/state/compact", params={"company_id": company_id})
    compact = compact_resp.json()

    async def gs(action: str, params: dict | None = None) -> list | dict:
        resp = await http.post(f"{session_url}/state/gs/query", params={"action": action}, json=params or {})
        return resp.json().get("result", resp.json())

    towns = await gs("get_towns")
    towns.sort(key=lambda t: t.get("population", 0), reverse=True)
    subsidies = await gs("get_subsidies")
    vehicles = await gs("get_vehicles", {"company_id": company_id})
    stations = await gs("get_stations", {"company_id": company_id})

    return {
        "compact": compact,
        "towns": towns,
        "subsidies": subsidies,
        "vehicles": vehicles,
        "stations": stations,
    }


# ── Planner node ───────────────────────────────────────────────────────

async def plan(llm: ChatOpenAI, obs: dict, company_id: int) -> list[str]:
    """Generate strategic goals from current observations."""
    prompt = PLANNER_PROMPT.format(
        company_id=company_id,
        compact=json.dumps(obs["compact"], indent=2),
        towns=json.dumps(obs["towns"][:10], indent=2),
        subsidies=json.dumps(obs["subsidies"], indent=2),
        vehicles=json.dumps(obs["vehicles"], indent=2),
        stations=json.dumps(obs["stations"], indent=2),
    )
    response = await llm.ainvoke([
        SystemMessage(content="You are a strategic transport planner."),
        HumanMessage(content=prompt),
    ])
    try:
        goals = json.loads(response.content)
        if isinstance(goals, list):
            logger.info("Planner set %d goal(s): %s", len(goals), goals)
            return goals
    except json.JSONDecodeError:
        pass
    logger.warning("Planner output unparseable: %.200s", response.content)
    return ["Build a bus route between the two largest towns"]


# ── Executor node ──────────────────────────────────────────────────────

async def execute(llm: ChatOpenAI, obs: dict, goal: str, company_id: int) -> list[dict]:
    """Generate tactical actions to progress toward a goal."""
    prompt = EXECUTOR_PROMPT.format(
        company_id=company_id,
        goal=goal,
        compact=json.dumps(obs["compact"], indent=2),
        vehicles=json.dumps(obs["vehicles"], indent=2),
        stations=json.dumps(obs["stations"], indent=2),
        action_format=ACTION_FORMAT_INSTRUCTIONS,
        action_reference=ACTION_REFERENCE,
    )
    response = await llm.ainvoke([
        SystemMessage(content="You are a tactical OpenTTD action executor."),
        HumanMessage(content=prompt),
    ])
    return _parse_actions(response.content)


# ── Agent loop ─────────────────────────────────────────────────────────

async def run_agent(
    base_url: str,
    session_id: str,
    company_id: int,
    model: str,
    poll_interval: float,
    replan_interval: int,
) -> None:
    session_url = f"{base_url}/sessions/{session_id}"
    llm = ChatOpenAI(model=model, temperature=0.2)

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        # Register
        await http.post(f"{session_url}/agents/connect", json={
            "agent_id": "langgraph_agent", "name": "LangGraph Planner-Executor", "company_scope": [company_id],
        })
        logger.info("Connected to session %s as company %d", session_id, company_id)

        goals: list[str] = []
        goal_index = 0
        cycle = 0

        while True:
            # ── Observe ──
            obs = await observe(http, session_url, company_id)
            logger.info("Cycle %d | date=%s | vehicles=%d | goals=%d",
                        cycle, obs["compact"].get("game_date", "?"),
                        len(obs["vehicles"]), len(goals))

            # ── Plan (every N cycles or when no goals) ──
            if not goals or cycle % replan_interval == 0:
                goals = await plan(llm, obs, company_id)
                goal_index = 0

            # ── Execute (pick current goal, generate actions) ──
            current_goal = goals[goal_index % len(goals)]
            logger.info("Executing toward goal: %s", current_goal)

            actions = await execute(llm, obs, current_goal, company_id)
            logger.info("Executor proposed %d action(s)", len(actions))

            # ── Interpret & Submit ──
            if actions:
                resp = await http.post(
                    f"{session_url}/actions/interpret",
                    json=actions,
                    params={"company_id": company_id},
                )
                results = resp.json()
                successes = sum(1 for r in results if r.get("status") == "success")
                failures = sum(1 for r in results if r.get("status") != "success")
                logger.info("  Results: %d success, %d failed", successes, failures)

                # Advance to next goal after executing
                goal_index += 1

            cycle += 1
            await asyncio.sleep(poll_interval)


def _parse_actions(raw: str) -> list[dict]:
    """Extract JSON action array from LLM response."""
    import re
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangGraph planner-executor nttd agent")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--replan-interval", type=int, default=5, help="Re-plan every N cycles")
    args = parser.parse_args()

    asyncio.run(run_agent(
        base_url=args.base_url,
        session_id=args.session_id,
        company_id=args.company_id,
        model=args.model,
        poll_interval=args.poll_interval,
        replan_interval=args.replan_interval,
    ))
