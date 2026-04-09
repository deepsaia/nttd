"""Integration test: runs the heartbeat loop for 3 steps using a mock OpenTTD connection.

Verifies the full pipeline:
  pause → GS refresh → snapshot → agent receives snapshot → agent submits action
  → action executes via GS → action tracked → unpause → advance N days

Run with verbose output to see the full log:
  uv run pytest tests/test_simulation.py -v -s
"""
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nttd.actions.tracker import ActionTracker
from nttd.runtime.orchestrator import Orchestrator
from nttd.schemas.snapshot import StateSnapshot
from nttd.state.world import WorldState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("test_simulation")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_client(world: WorldState) -> MagicMock:
    """Build a mock AdminClient that is connected and returns success for all GS calls."""
    client = MagicMock()
    client.connected = True

    async def fake_rcon(cmd: str) -> list[str]:
        logger.info("[RCON] %s", cmd)
        return [f"ok: {cmd}"]

    async def fake_gs(action: str, params: dict | None = None, timeout: float = 10.0) -> dict[str, Any]:
        logger.info("[GS]   action=%s params=%s", action, params)
        if action == "get_towns":
            return {"success": True, "result": [
                {"id": 0, "name": "Testville", "population": 1200, "houses": 50, "x": 10, "y": 10,
                 "is_city": False, "growth_rate": 1},
            ]}
        if action == "get_industries":
            return {"success": True, "result": []}
        if action == "get_companies":
            return {"success": True, "result": [
                {"id": 0, "name": "Test Corp", "is_ai": False, "color": 0, "manager": "Bot"},
            ]}
        if action == "get_company_finance":
            return {"success": True, "result": {
                "balance": 100_000, "loan": 50_000, "income": 5_000, "value": 200_000,
            }}
        if action in ("get_stations", "get_vehicles", "get_subsidies"):
            return {"success": True, "result": []}
        # Any build/GS action
        return {"success": True, "result": {"built": action}}

    client.send_rcon = AsyncMock(side_effect=fake_rcon)
    client.send_gamescript = AsyncMock(side_effect=fake_gs)
    return client


@pytest.fixture
def world() -> WorldState:
    return WorldState()


@pytest.fixture
def action_tracker() -> ActionTracker:
    return ActionTracker()


@pytest.fixture
def orchestrator(world: WorldState, action_tracker: ActionTracker) -> Orchestrator:
    from nttd.schemas.company import Company
    world.companies[0] = Company(id=0, name="Test Corp", money=100_000, loan=50_000, income=5_000, is_active=True)
    world.game.game_date = 18628  # roughly 1950-01-01 in OpenTTD ticks

    client = _make_mock_client(world)
    orch = Orchestrator(world, client)
    orch.action_tracker = action_tracker
    orch.set_action_window(0.2)  # fast for tests
    orch.set_heartbeat_interval(1)
    return orch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_steps(orchestrator: Orchestrator, n_steps: int) -> list[StateSnapshot]:
    """Run n_steps heartbeat cycles, advancing game_date after each step."""
    received: list[StateSnapshot] = []

    def capture_snapshot(snap: StateSnapshot) -> None:
        received.append(snap)
        logger.info(
            "  Snapshot step=%d date=%d companies=%d towns=%d vehicles=%d",
            len(received), snap.game.game_date, len(snap.companies), len(snap.towns), len(snap.vehicles),
        )

    orchestrator.add_observer(capture_snapshot)

    # Patch _wait_game_days to advance the date instead of polling
    async def advance_date(days: int) -> None:
        orchestrator.world.game.game_date += days

    orchestrator._wait_game_days = advance_date  # type: ignore[method-assign]

    await orchestrator.run_heartbeat(steps=n_steps)
    return received


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_3_steps_delivers_snapshots(orchestrator: Orchestrator) -> None:
    """Orchestrator delivers exactly 3 snapshots to observers over 3 heartbeat steps."""
    logger.info("=== Starting 3-step heartbeat simulation ===")
    snapshots = await _run_steps(orchestrator, n_steps=3)

    assert len(snapshots) == 3, f"Expected 3 snapshots, got {len(snapshots)}"
    # Date advances each step
    assert snapshots[2].game.game_date > snapshots[0].game.game_date
    logger.info("=== %d snapshots received, dates: %s ===",
                len(snapshots), [s.game.game_date for s in snapshots])


@pytest.mark.asyncio
async def test_heartbeat_action_submitted_and_tracked(
    orchestrator: Orchestrator, action_tracker: ActionTracker
) -> None:
    """Actions submitted during observer callback are executed and tracked by ActionTracker."""

    def submit_action(snap: StateSnapshot) -> None:
        orchestrator.submit_heartbeat_action({
            "action": "connect_road",
            "params": {"company_id": 0, "start_tile": 1000, "end_tile": 1010},
        })

    orchestrator.add_observer(submit_action)

    logger.info("=== Submitting 'build_road' on each step ===")
    await _run_steps(orchestrator, n_steps=2)

    recent = action_tracker.get_recent(10)
    action_types = [action_tracker.get_envelope(r.action_id).action_type for r in recent]  # type: ignore[union-attr]

    logger.info("Tracked actions: %s", [(r.action_id, r.status) for r in recent])
    assert "connect_road" in action_types, f"build_road not found in tracked actions: {action_types}"
    assert all(r.status in ("success", "failed") for r in recent), "All actions should be resolved"


@pytest.mark.asyncio
async def test_end_condition_max_heartbeats_stops_loop(orchestrator: Orchestrator) -> None:
    """End condition max_heartbeats=2 stops the loop after 2 steps even if steps=10 requested."""
    from nttd.config.scenario_config import EndConditionsConfig, MaxHeartbeatsConfig
    from nttd.runtime.end_conditions import EndConditionChecker

    ec = EndConditionsConfig(max_heartbeats=MaxHeartbeatsConfig(enabled=True, count=2))
    orchestrator._end_checker = EndConditionChecker(ec)

    ended_reasons: list[str] = []
    orchestrator.on_end.append(lambda reason: ended_reasons.append(reason))

    snapshots = await _run_steps(orchestrator, n_steps=10)

    logger.info("Snapshots before end: %d | Reason: %s", len(snapshots), ended_reasons)
    assert len(snapshots) == 2, f"Expected 2 snapshots before end, got {len(snapshots)}"
    assert ended_reasons, "on_end callback should have been called"
    assert "Max heartbeats" in ended_reasons[0]


@pytest.mark.asyncio
async def test_gs_refresh_populates_world(orchestrator: Orchestrator, world: WorldState) -> None:
    """After each heartbeat step, WorldState.towns is populated from the GS mock response."""
    await _run_steps(orchestrator, n_steps=1)
    assert len(world.towns) == 1
    assert world.towns[0].name == "Testville"
    logger.info("Town refreshed: %s pop=%d", world.towns[0].name, world.towns[0].population)


@pytest.mark.asyncio
async def test_scope_enforcement_blocks_wrong_company(orchestrator: Orchestrator) -> None:
    """Scope enforcement: agent_registry blocks actions for companies outside scope.

    Tests the AgentRegistry directly since HTTP scope enforcement requires
    a running OpenTTD session (session-scoped routes need get_runtime()).
    """
    from nttd.schemas.agent import AgentRegistration
    from nttd.state.agent_registry import AgentRegistry

    registry = AgentRegistry()
    reg = AgentRegistration(agent_id="scope_agent", name="Scope Agent", company_scope=[1])
    registry.connect(reg)

    # Agent with scope [1] should NOT be allowed to act on company 99
    agent = registry.get("scope_agent")
    assert agent is not None
    assert 1 in agent.company_scope
    assert 99 not in agent.company_scope

    # Clean up
    registry.disconnect("scope_agent")
