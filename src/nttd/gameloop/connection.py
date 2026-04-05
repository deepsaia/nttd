"""AgentConnection — runs a single agent's observe-decide-interpret-execute cycle."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from examples.agent_instructions import get_bus_agent_prompt
from nttd.gameloop.adapters.base import BaseAdapter
from nttd.gameloop.observation_tools import ObservationToolkit
from nttd.gameloop.schemas import AgentConfig, ConnectionStatus
from nttd.gameloop.tracker import ConnectionTracker
from nttd.interpreter.parser import parse_action_list
from nttd.interpreter.validator import validate_actions

if TYPE_CHECKING:
    from nttd.runtime.session_runtime import SessionRuntime

logger = logging.getLogger(__name__)

_LLM_TIMEOUT_SECONDS = 120.0  # Multi-turn tool calling can take several rounds


class AgentConnection:
    """Manages the lifecycle and cycle loop for a single agent.

    Created by GameloopManager when an agent is registered.
    The cycle loop runs as an asyncio.Task and repeats:
      observe → decide (LLM) → parse → validate → execute → sleep
    """

    def __init__(
        self,
        connection_id: str,
        config: AgentConfig,
        runtime: SessionRuntime,
        adapter: BaseAdapter,
    ) -> None:
        self.connection_id = connection_id
        self.config = config
        self.runtime = runtime
        self.adapter = adapter
        self.tracker = ConnectionTracker(connection_id, runtime.session_id)
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False

        # Default instructions when none provided
        if not config.instructions:
            config.instructions = get_bus_agent_prompt(config.company_id)
            logger.info("Agent %s using default bus agent prompt", config.agent_id)

        # Build observation toolkit if tools are enabled
        self._toolkit: ObservationToolkit | None = None
        if config.observation_tools:
            self._toolkit = ObservationToolkit(runtime.admin_client, config.company_id)

    @property
    def status(self) -> str:
        """Current connection status string."""
        if self._running and self._task and not self._task.done():
            return "running"
        if self._task and self._task.done():
            return "stopped"
        return "registered"

    def to_status(self) -> ConnectionStatus:
        """Build a ConnectionStatus snapshot."""
        return ConnectionStatus(
            connection_id=self.connection_id,
            agent_id=self.config.agent_id,
            company_id=self.config.company_id,
            framework=self.config.framework,
            model=self.config.model,
            status=self.status,
            cycle_count=self.tracker.cycle_count,
            total_actions=self.tracker.total_actions,
            successful_actions=self.tracker.successful_actions,
            failed_actions=self.tracker.failed_actions,
            avg_cycle_ms=round(self.tracker.avg_cycle_ms, 1),
            avg_decide_ms=round(self.tracker.avg_decide_ms, 1),
            last_error=self.tracker.last_error,
        )

    def start(self) -> None:
        """Spawn the cycle loop as an asyncio task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"agent:{self.config.agent_id}")
        logger.info("Agent %s started (connection %s)", self.config.agent_id, self.connection_id)

    async def stop(self) -> None:
        """Stop the cycle loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.adapter.close()
        logger.info("Agent %s stopped (connection %s)", self.config.agent_id, self.connection_id)

    async def _run(self) -> None:
        """Main cycle loop: observe → decide → interpret → execute → sleep."""
        logger.info(
            "Agent %s cycle loop started (company=%d, framework=%s, poll=%.1fs)",
            self.config.agent_id, self.config.company_id,
            self.config.framework, self.config.poll_interval,
        )

        while self._running:
            try:
                await self._run_one_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Agent %s cycle error", self.config.agent_id)
                self.tracker.record_error("cycle_exception")

            # Wait for next cycle
            wait = max(0.5, self.config.poll_interval)
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break

    async def _run_one_cycle(self) -> None:
        """Execute a single observe-decide-interpret-execute cycle."""
        self.tracker.start_cycle()

        # 1. Observe
        self.tracker.start_observe()
        observation = await self._observe()
        self.tracker.end_observe(observation)

        game_date = observation.get("game_date", 0)

        # 2. Decide (call LLM via adapter, with optional tool calling)
        tool_schemas = self._toolkit.get_openai_schemas() if self._toolkit else None
        tool_executor = self._toolkit.execute if self._toolkit else None

        self.tracker.start_decide()
        try:
            raw_output = await asyncio.wait_for(
                self.adapter.decide(
                    observation, self.config.instructions,
                    observation_tools=tool_schemas,
                    tool_executor=tool_executor,
                ),
                timeout=_LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self.tracker.record_error("llm_timeout")
            self.tracker.end_decide()
            self.tracker.end_cycle(game_date, 0, 0, 0, 0)
            logger.warning("Agent %s LLM call timed out", self.config.agent_id)
            return
        except Exception as exc:
            self.tracker.record_error(str(exc)[:200])
            self.tracker.end_decide()
            self.tracker.end_cycle(game_date, 0, 0, 0, 0)
            logger.warning("Agent %s LLM call failed: %s", self.config.agent_id, exc)
            return
        self.tracker.end_decide()

        logger.info("Agent %s raw LLM output: %r", self.config.agent_id, raw_output[:1000])

        # 3. Parse & Validate
        actions = parse_action_list(raw_output)
        if len(actions) > self.config.max_actions_per_cycle:
            logger.warning(
                "Agent %s proposed %d actions, truncating to %d",
                self.config.agent_id, len(actions), self.config.max_actions_per_cycle,
            )
            actions = actions[: self.config.max_actions_per_cycle]

        errors = validate_actions(actions)
        valid_actions = [a for i, a in enumerate(actions) if i not in errors]
        if errors:
            logger.info(
                "Agent %s: %d/%d actions invalid",
                self.config.agent_id, len(errors), len(actions),
            )

        # 4. Execute
        self.tracker.start_execute()
        succeeded = 0
        failed = 0
        if valid_actions:
            results = await self._execute(valid_actions)
            for r in results:
                if r.get("status") == "success":
                    succeeded += 1
                else:
                    failed += 1
        self.tracker.end_execute()

        # 5. Record
        record = self.tracker.end_cycle(
            game_date=game_date,
            actions_proposed=len(actions),
            actions_executed=len(valid_actions),
            actions_succeeded=succeeded,
            actions_failed=failed,
        )

        logger.info(
            "Agent %s cycle %d: %d proposed, %d executed (%d ok, %d fail) in %.0fms",
            self.config.agent_id, record.cycle_number,
            record.actions_proposed, record.actions_executed,
            record.actions_succeeded, record.actions_failed,
            record.total_ms,
        )

    async def _observe(self) -> dict[str, Any]:
        """Build the observation for this agent from the runtime's WorldState."""
        world = self.runtime.world
        game = world.game

        if self.config.observation_mode == "full":
            snapshot = world.snapshot()
            return json.loads(snapshot.model_dump_json())

        # Compact mode — build a lightweight dict directly
        company_id = self.config.company_id
        company = world.companies.get(company_id)
        company_dict: dict[str, Any] | None = None
        if company:
            company_dict = {
                "id": company.id,
                "name": company.name,
                "balance": company.money,
                "loan": company.loan,
                "income": company.income,
                "company_value": company.value,
            }

        company_vehicles = [
            v for v in world.vehicles.values()
            if v.company_id == company_id
        ]
        vehicles_dict = {
            "total": len(company_vehicles),
            "in_depot": sum(1 for v in company_vehicles if v.in_depot),
        }

        company_stations = [
            s for s in world.stations.values()
            if s.company_id == company_id
        ]

        top_towns = sorted(
            world.towns.values(),
            key=lambda t: t.population,
            reverse=True,
        )[:10]

        return {
            "game_date": game.game_date,
            "paused": game.paused,
            "company": company_dict,
            "vehicles": vehicles_dict,
            "total_stations": len(company_stations),
            "total_towns": len(world.towns),
            "top_towns": [
                {"id": t.id, "name": t.name, "population": t.population}
                for t in top_towns
            ],
        }

    async def _execute(self, actions: list[Any]) -> list[dict[str, Any]]:
        """Execute validated actions via GS commands through the admin client."""
        results: list[dict[str, Any]] = []
        for action in actions:
            params = {**action.parameters, "company_id": self.config.company_id}
            try:
                gs_result = await self.runtime.admin_client.send_gamescript(
                    action.action_type, params,
                )
                if gs_result.get("success"):
                    logger.info(
                        "Agent %s action %s OK: %s",
                        self.config.agent_id, action.action_type, gs_result.get("result", {}),
                    )
                    results.append({"status": "success", "result": gs_result.get("result", {})})
                else:
                    error = gs_result.get("error", "GS returned failure")
                    logger.info(
                        "Agent %s action %s FAILED: %s (params=%s)",
                        self.config.agent_id, action.action_type, error, params,
                    )
                    results.append({"status": "failed", "error": error})
            except Exception as exc:
                logger.warning(
                    "Agent %s action %s failed: %s",
                    self.config.agent_id, action.action_type, exc,
                )
                results.append({"status": "error", "error": str(exc)})
        return results
