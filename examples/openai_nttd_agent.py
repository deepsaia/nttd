#!/usr/bin/env python3
"""OpenAI Agents SDK agent for nttd — uses function calling for observations.

The agent uses OpenAI's native function calling to query game state,
then outputs a structured action list for the interpreter.

Usage:
    OPENAI_API_KEY=sk-... uv run python examples/openai_nttd_agent.py \
        --session-id ses_abc123 --company-id 0

Requirements:
    pip install openai httpx
"""

import argparse
import asyncio
import json
import logging

import httpx
from openai import AsyncOpenAI

from examples.agent_instructions import get_bus_agent_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("openai_nttd")


# ── Tool definitions (OpenAI function calling schema) ──────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_towns",
            "description": "List all towns on the map with name, population, and coordinates.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_engines",
            "description": "List purchasable engines. vehicle_type: 0=train, 1=road, 2=ship, 3=air.",
            "parameters": {
                "type": "object",
                "properties": {"vehicle_type": {"type": "integer", "default": 1}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_vehicles",
            "description": "List your vehicles with id, type, name, and profit.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_bus_stop_spots",
            "description": "Find road tiles near a town suitable for building bus stops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "town_id": {"type": "integer", "description": "Town ID to search near"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["town_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_depot_spots",
            "description": "Find road tiles near a town suitable for building a road depot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "town_id": {"type": "integer", "description": "Town ID to search near"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["town_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_finance",
            "description": "Get your detailed financials: balance, loan, income, expenses.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_actions",
            "description": "Validate a proposed action list without executing. Returns valid/invalid per action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action_type": {"type": "string"},
                                "parameters": {"type": "object"},
                            },
                        },
                    },
                },
                "required": ["actions"],
            },
        },
    },
]


# ── Tool execution (HTTP calls to nttd) ───────────────────────────────

async def execute_tool(
    http: httpx.AsyncClient, session_url: str, company_id: int,
    name: str, arguments: dict,
) -> str:
    """Execute an observation tool by calling the nttd REST API."""
    gs_tools = {"get_towns", "get_engines", "get_vehicles", "find_bus_stop_spots",
                "find_depot_spots", "get_company_finance"}

    if name in gs_tools:
        params = dict(arguments)
        params.setdefault("company_id", company_id)
        resp = await http.post(
            f"{session_url}/state/gs/query",
            params={"action": name},
            json=params,
        )
        return json.dumps(resp.json().get("result", resp.json()))

    if name == "validate_actions":
        resp = await http.post(
            f"{session_url}/actions/interpret/validate",
            json=arguments.get("actions", []),
        )
        return resp.text

    return json.dumps({"error": f"Unknown tool: {name}"})


# ── Agent loop ─────────────────────────────────────────────────────────

async def run_agent(
    base_url: str,
    session_id: str,
    company_id: int,
    model: str,
    poll_interval: float,
) -> None:
    session_url = f"{base_url}/sessions/{session_id}"
    system_prompt = get_bus_agent_prompt(company_id)
    client = AsyncOpenAI()

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        # Register as agent
        await http.post(f"{session_url}/agents/connect", json={
            "agent_id": f"openai_{model}", "name": f"OpenAI {model}", "company_scope": [company_id],
        })
        logger.info("Connected to session %s as company %d", session_id, company_id)

        cycle = 0

        while True:
            # ── Observe ──
            resp = await http.get(f"{session_url}/state/compact", params={"company_id": company_id})
            compact = resp.json()

            logger.info("Cycle %d | date=%s | vehicles=%s",
                        cycle, compact.get("game_date", "?"),
                        compact.get("vehicles", {}).get("total", 0))

            # Build messages for this cycle
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": (
                    f"Game state (cycle {cycle}):\n"
                    f"{json.dumps(compact, indent=2)}\n\n"
                    "Analyze the state, use tools to gather details if needed, "
                    "then output your action list."
                )},
            ]

            # ── Decide (multi-turn with tool calling) ──
            for _ in range(8):  # max tool-calling rounds
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                )
                msg = response.choices[0].message
                messages.append(msg.model_dump())

                if not msg.tool_calls:
                    break

                # Execute each tool call
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    result = await execute_tool(http, session_url, company_id, tc.function.name, args)
                    logger.info("  Tool %s → %d bytes", tc.function.name, len(result))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            # ── Parse action list from final response ──
            raw_output = msg.content or ""
            actions = _parse_actions(raw_output)
            logger.info("LLM proposed %d action(s)", len(actions))

            # ── Interpret & Execute ──
            if actions:
                resp = await http.post(
                    f"{session_url}/actions/interpret",
                    json=actions,
                    params={"company_id": company_id},
                )
                results = resp.json()
                for r in results:
                    logger.info("  %s: %s %s", r.get("action_id", "?"), r.get("status", "?"), r.get("error", ""))

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
    parser = argparse.ArgumentParser(description="OpenAI nttd agent")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--company-id", type=int, default=0)
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    args = parser.parse_args()

    asyncio.run(run_agent(
        base_url=args.base_url,
        session_id=args.session_id,
        company_id=args.company_id,
        model=args.model,
        poll_interval=args.poll_interval,
    ))
