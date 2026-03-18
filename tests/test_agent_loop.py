"""Agent loop integration test.

Tests ScriptedAgent.decide() through all phases using mocked NttdTools.
Proves the full agent decision cycle works without a running OpenTTD server.

Run with verbose output to see what each phase does:
    uv run pytest tests/test_agent_loop.py -v -s

NOTE: Agents are external processes — in production they run as:
    uv run python agents/scripted_agent.py --company-id 0
This test validates their logic in isolation by mocking the tool layer.
"""
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.base import AgentContext, GameAction
from agents.scripted_agent import ScriptedAgent
from agents.tools import NttdTools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("test_agent_loop")

_TOWNS = [
    {"id": 0, "name": "Townington", "population": 5000, "x": 10, "y": 10, "is_city": True},
    {"id": 1, "name": "Villageville", "population": 3000, "x": 40, "y": 40, "is_city": False},
    {"id": 2, "name": "Hamleton", "population": 800, "x": 70, "y": 20, "is_city": False},
]

_ENGINES = [
    {"id": 10, "name": "Pickup Truck", "cargo_label": "PASS", "max_speed": 60, "running_cost": 100},
    {"id": 11, "name": "Diesel Bus", "cargo_label": "PASS", "max_speed": 80, "running_cost": 150},
]


def _make_tools(
    towns: list[dict] | None = None,
    stop_spots: list[dict] | None = None,
    depot_spots: list[dict] | None = None,
    engines: list[dict] | None = None,
    vehicles: list[dict] | None = None,
) -> NttdTools:
    """Return a NttdTools mock pre-loaded with realistic data."""
    tools = MagicMock(spec=NttdTools)
    tools.get_towns.return_value = towns if towns is not None else _TOWNS
    tools.find_bus_stop_spots.return_value = (
        stop_spots if stop_spots is not None
        else [{"tile": 1000, "x": 10, "y": 10}, {"tile": 1001, "x": 11, "y": 10}]
    )
    tools.find_depot_spots.return_value = (
        depot_spots if depot_spots is not None
        else [{"tile": 2000, "x": 10, "y": 12}]
    )
    tools.get_engines.return_value = engines if engines is not None else _ENGINES
    tools.get_vehicles.return_value = vehicles if vehicles is not None else []
    return tools


def _make_context(
    heartbeat_count: int = 0,
    compact: dict[str, Any] | None = None,
) -> AgentContext:
    return AgentContext(
        compact=compact or {"game_date": 18628, "paused": False, "mode": "heartbeat",
                            "vehicles": {"total": 0, "in_depot": 0, "by_type": {}}},
        history=[],
        company_id=0,
        game_date=18628,
        heartbeat_count=heartbeat_count,
    )


def _make_agent() -> ScriptedAgent:
    agent = ScriptedAgent(base_url="http://localhost:8000", company_id=0, agent_id="test_scripted")
    # Prevent real NttdClient from being used (no server running)
    agent.client = MagicMock()
    agent.client.base_url = "http://localhost:8000"
    agent.client.company_id = 0
    return agent


# ---------------------------------------------------------------------------
# Phase tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scout_phase_picks_largest_towns() -> None:
    """Scout phase queries towns and picks the two most populous."""
    agent = _make_agent()
    tools = _make_tools()
    agent._tools = tools

    actions = await agent.decide(_make_context(heartbeat_count=0))

    logger.info("Scout phase: phase=%s town_a=%s town_b=%s",
                agent._phase, agent._town_a and agent._town_a["name"],
                agent._town_b and agent._town_b["name"])

    assert actions == [], "Scout phase should return no actions"
    assert agent._phase == "build_stops"
    assert agent._town_a is not None
    assert agent._town_b is not None
    assert agent._town_a["name"] == "Townington"   # highest population
    assert agent._town_b["name"] == "Villageville"  # second highest


@pytest.mark.asyncio
async def test_build_stops_phase_emits_correct_actions() -> None:
    """Build-stops phase calls find_bus_stop_spots + find_depot_spots and emits build actions.

    Both stops can be built in a single heartbeat because _stop_a is set before
    the _stop_b guard is checked — the agent is opportunistic within one cycle.
    """
    agent = _make_agent()
    tools = _make_tools()
    agent._tools = tools

    agent._phase = "build_stops"
    agent._town_a = _TOWNS[0]
    agent._town_b = _TOWNS[1]

    actions = await agent.decide(_make_context(heartbeat_count=1))

    action_types = [a.action for a in actions]
    logger.info("Build-stops phase: actions=%s phase_after=%s", action_types, agent._phase)

    # Both stops + depot built in one heartbeat
    assert action_types.count("build_road_stop") == 2
    assert "build_road_depot" in action_types
    assert agent._stop_a == 1000
    assert agent._stop_b == 1000   # same mock tile is fine; the logic accepts it
    assert agent._depot_tile == 2000
    # Phase advances immediately since all conditions are met
    assert agent._phase == "buy_vehicle"


@pytest.mark.asyncio
async def test_build_stops_phase_waits_when_no_candidates() -> None:
    """Phase stays on build_stops and emits no actions if no candidate tiles are found."""
    agent = _make_agent()
    tools = _make_tools(stop_spots=[], depot_spots=[])
    agent._tools = tools

    agent._phase = "build_stops"
    agent._town_a = _TOWNS[0]
    agent._town_b = _TOWNS[1]

    actions = await agent.decide(_make_context(heartbeat_count=1))
    logger.info("Build-stops (no candidates): actions=%s phase=%s", actions, agent._phase)

    assert actions == []
    assert agent._phase == "build_stops"   # stuck, no candidates yet


@pytest.mark.asyncio
async def test_buy_vehicle_phase_creates_vehicle_and_sets_orders() -> None:
    """Buy-vehicle phase buys an engine and adds two station orders."""
    agent = _make_agent()
    tools = _make_tools(vehicles=[{"id": 42, "type": "road", "company_id": 0, "in_depot": True}])
    agent._tools = tools

    agent._phase = "buy_vehicle"
    agent._stop_a = 1000
    agent._stop_b = 1005
    agent._depot_tile = 2000

    actions = await agent.decide(_make_context(heartbeat_count=3))
    action_types = [a.action for a in actions]
    logger.info("Buy-vehicle phase: actions=%s vehicle_id=%s phase=%s",
                action_types, agent._vehicle_id, agent._phase)

    assert "buy_vehicle" in action_types
    assert "add_order" in action_types
    assert "start_vehicle" in action_types
    assert action_types.count("add_order") == 2    # one per station

    buy = next(a for a in actions if a.action == "buy_vehicle")
    assert buy.params["engine_id"] == 10
    assert buy.params["depot_tile"] == 2000

    orders = [a for a in actions if a.action == "add_order"]
    destinations = {a.params["destination"] for a in orders}
    assert destinations == {1000, 1005}

    assert agent._vehicle_id == 42
    assert agent._phase == "running"


@pytest.mark.asyncio
async def test_running_phase_rescues_stuck_vehicle() -> None:
    """Running phase emits start_vehicle if a vehicle is stuck in depot."""
    agent = _make_agent()
    agent._tools = _make_tools()
    agent._phase = "running"
    agent._vehicle_id = 42

    compact = {
        "game_date": 18700,
        "paused": False,
        "mode": "heartbeat",
        "vehicles": {"total": 1, "in_depot": 1, "avg_profit_this_year": 0, "by_type": {"road": 1}},
    }
    actions = await agent.decide(_make_context(heartbeat_count=10, compact=compact))
    action_types = [a.action for a in actions]
    logger.info("Running phase (stuck): actions=%s", action_types)

    assert "start_vehicle" in action_types
    assert actions[0].params["vehicle_id"] == 42


@pytest.mark.asyncio
async def test_running_phase_no_actions_when_moving() -> None:
    """Running phase returns no actions when vehicles are not stuck."""
    agent = _make_agent()
    agent._tools = _make_tools()
    agent._phase = "running"
    agent._vehicle_id = 42

    compact = {
        "game_date": 18700,
        "paused": False,
        "mode": "heartbeat",
        "vehicles": {"total": 1, "in_depot": 0, "avg_profit_this_year": 500, "by_type": {"road": 1}},
    }
    actions = await agent.decide(_make_context(heartbeat_count=11, compact=compact))
    logger.info("Running phase (moving): actions=%s profit=%s",
                [a.action for a in actions],
                compact["vehicles"]["avg_profit_this_year"])

    assert actions == []


# ---------------------------------------------------------------------------
# Full multi-step simulation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_agent_loop_all_phases() -> None:
    """Run through all phases in sequence and verify state evolution."""
    agent = _make_agent()
    # Vehicles list grows after buy step
    vehicles_after_buy = [{"id": 42, "type": "road", "company_id": 0, "in_depot": True}]
    tools_before_buy = _make_tools(vehicles=[])
    tools_after_buy = _make_tools(vehicles=vehicles_after_buy)
    agent._tools = tools_before_buy

    all_actions: list[list[GameAction]] = []

    for hb in range(5):
        if hb == 3:
            # Simulate vehicle appearing in world after buy
            agent._tools = tools_after_buy
        compact = {
            "game_date": 18628 + hb * 30,
            "paused": False,
            "mode": "heartbeat",
            "vehicles": {
                "total": 1 if hb >= 4 else 0,
                "in_depot": 0,
                "avg_profit_this_year": 200 if hb >= 4 else 0,
                "by_type": {"road": 1} if hb >= 4 else {},
            },
        }
        context = _make_context(heartbeat_count=hb, compact=compact)
        actions = await agent.decide(context)
        all_actions.append(actions)
        logger.info(
            "HB %d | phase=%-12s | actions=%s",
            hb,
            agent._phase,
            [a.action for a in actions] or "(none)",
        )

    phases = ["build_stops", "build_stops", "buy_vehicle", "running", "running"]
    assert agent._phase == "running", f"Expected final phase 'running', got '{agent._phase}'"

    # At least one heartbeat should have submitted build actions
    submitted = [a.action for step in all_actions for a in step]
    assert "build_road_stop" in submitted
    assert "build_road_depot" in submitted
    assert "buy_vehicle" in submitted
    assert "add_order" in submitted
    assert "start_vehicle" in submitted
    logger.info("All submitted actions: %s", submitted)
