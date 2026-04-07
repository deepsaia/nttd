"""AgentConnection — runs a single agent's observe-decide-interpret-execute cycle."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from examples.agent_instructions import (
    get_air_agent_prompt,
    get_general_agent_prompt,
    get_rail_agent_prompt,
    get_road_agent_prompt,
    get_water_agent_prompt,
)
from nttd.gameloop.adapters.base import BaseAdapter
from nttd.gameloop.observation_tools import ObservationToolkit
from nttd.gameloop.schemas import AgentConfig, ConnectionStatus
from nttd.gameloop.tracker import ConnectionTracker
from nttd.interpreter.parser import parse_action_list
from nttd.interpreter.validator import validate_actions
from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult, ActionStatus

if TYPE_CHECKING:
    from nttd.runtime.session_runtime import SessionRuntime

logger = logging.getLogger(__name__)

_LLM_TIMEOUT_SECONDS = 120.0  # Multi-turn tool calling can take several rounds

_PROMPT_MAP: dict[str, Any] = {
    "road": get_road_agent_prompt,
    "rail": get_rail_agent_prompt,
    "air": get_air_agent_prompt,
    "water": get_water_agent_prompt,
    "general": get_general_agent_prompt,
}


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

        # Default instructions when none provided — select by agent_type
        if not config.instructions:
            prompt_fn = _PROMPT_MAP.get(config.agent_type, get_road_agent_prompt)
            config.instructions = prompt_fn(config.company_id)
            logger.info(
                "Agent %s using default %s prompt", config.agent_id, config.agent_type,
            )

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

        # Record agent start event and connection to DB
        self.runtime.recorder.record_event(
            game_date=self.runtime.world.game.game_date,
            event_type="agent_start",
            company_id=self.config.company_id,
            detail=self.config.agent_id,
        )
        self.runtime.recorder.record_agent_connection(
            connection_id=self.connection_id,
            agent_id=self.config.agent_id,
            company_id=self.config.company_id,
            framework=self.config.framework,
            model=self.config.model,
            observation_mode=self.config.observation_mode,
            poll_interval=self.config.poll_interval,
            started_at=datetime.now(timezone.utc),
        )

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

        # Record agent stop event
        self.runtime.recorder.record_event(
            game_date=self.runtime.world.game.game_date,
            event_type="agent_stop",
            company_id=self.config.company_id,
            detail=self.config.agent_id,
        )

        # Record connection stop with final aggregate stats to DB
        self.runtime.recorder.record_agent_connection(
            connection_id=self.connection_id,
            agent_id=self.config.agent_id,
            company_id=self.config.company_id,
            framework=self.config.framework,
            model=self.config.model,
            observation_mode=self.config.observation_mode,
            poll_interval=self.config.poll_interval,
            stopped_at=datetime.now(timezone.utc),
            total_cycles=self.tracker.cycle_count,
            total_actions=self.tracker.total_actions,
            successful_actions=self.tracker.successful_actions,
            failed_actions=self.tracker.failed_actions,
            avg_cycle_ms=round(self.tracker.avg_cycle_ms, 1),
            avg_decide_ms=round(self.tracker.avg_decide_ms, 1),
        )

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
            results = await self._execute(valid_actions, game_date)
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

        # Persist cycle record to DB
        self.runtime.recorder.record_agent_cycle(record)

        logger.info(
            "Agent %s cycle %d: %d proposed, %d executed (%d ok, %d fail) in %.0fms",
            self.config.agent_id, record.cycle_number,
            record.actions_proposed, record.actions_executed,
            record.actions_succeeded, record.actions_failed,
            record.total_ms,
        )

    async def _observe(self) -> dict[str, Any]:
        """Build the observation for this agent based on its snapshot class."""
        world = self.runtime.world
        game = world.game
        company_id = self.config.company_id

        # Resolve snapshot class
        class_name = self.config.effective_snapshot_class
        try:
            snap_class = self.runtime.snapshot_class_registry.get(class_name)
        except KeyError:
            logger.warning(
                "Agent %s: unknown snapshot class %r, falling back to compact",
                self.config.agent_id, class_name,
            )
            snap_class = self.runtime.snapshot_class_registry.get("compact")

        sections = snap_class.sections

        # "full" class returns the entire StateSnapshot as JSON
        if class_name == "full":
            snapshot = world.snapshot()
            return json.loads(snapshot.model_dump_json())

        # Build observation dict from requested sections
        obs: dict[str, Any] = {
            "game_date": game.game_date,
            "paused": game.paused,
        }

        if "company" in sections:
            company = world.companies.get(company_id)
            if company:
                obs["company"] = {
                    "id": company.id,
                    "name": company.name,
                    "balance": company.money,
                    "loan": company.loan,
                    "income": company.income,
                    "company_value": company.value,
                    "profit_last_year": company.profit_last_year,
                }
                if self.config.include_finance:
                    try:
                        fin = await self.runtime.admin_client.send_gamescript(
                            "get_company_finance", {"company_id": company_id}, timeout=10.0,
                        )
                        if fin.get("success"):
                            fin_data = fin.get("result", {})
                            obs["company"]["max_loan"] = fin_data.get("max_loan")
                            obs["company"]["q1_income"] = fin_data.get("q1_income")
                            obs["company"]["q1_expenses"] = fin_data.get("q1_expenses")
                    except Exception:
                        logger.debug("Agent %s finance fetch failed", self.config.agent_id)

        if "vehicles_detail" in sections:
            company_vehicles = [v for v in world.vehicles.values() if v.company_id == company_id]
            obs["vehicles"] = [
                {
                    "id": v.id, "type": v.type, "name": v.name,
                    "running": v.running, "in_depot": v.in_depot,
                    "profit_this_year": v.profit_this_year,
                    "profit_last_year": v.profit_last_year,
                    "current_speed": v.current_speed,
                    "age": v.age,
                    "order_count": v.order_count,
                    "orders": [
                        {
                            "destination": o.destination,
                            "flags": o.flags,
                            "is_goto_station": o.is_goto_station,
                            "is_goto_depot": o.is_goto_depot,
                        }
                        for o in v.orders
                    ],
                }
                for v in company_vehicles
            ]
        elif "vehicles" in sections:
            company_vehicles = [v for v in world.vehicles.values() if v.company_id == company_id]
            obs["vehicles"] = [
                {
                    "id": v.id, "type": v.type, "name": v.name,
                    "running": v.running, "in_depot": v.in_depot,
                    "profit_this_year": v.profit_this_year,
                }
                for v in company_vehicles
            ]
        elif "vehicles_summary" in sections:
            company_vehicles = [v for v in world.vehicles.values() if v.company_id == company_id]
            obs["vehicles"] = {
                "total": len(company_vehicles),
                "in_depot": sum(1 for v in company_vehicles if v.in_depot),
            }

        if "stations_detail" in sections:
            company_stations = [s for s in world.stations.values() if s.company_id == company_id]
            obs["stations"] = [
                {
                    "id": s.id, "name": s.name, "x": s.x, "y": s.y,
                    "has_rail": s.has_rail, "has_bus": s.has_bus,
                    "has_truck": s.has_truck, "has_airport": s.has_airport,
                    "has_dock": s.has_dock,
                    "cargo_waiting": [
                        {"cargo_label": cw.cargo_label, "waiting": cw.waiting}
                        for cw in s.cargo_waiting
                    ],
                }
                for s in company_stations
            ]
        elif "stations" in sections:
            company_stations = [s for s in world.stations.values() if s.company_id == company_id]
            obs["stations"] = [
                {"id": s.id, "name": s.name, "x": s.x, "y": s.y}
                for s in company_stations
            ]
        elif "stations_count" in sections:
            company_stations = [s for s in world.stations.values() if s.company_id == company_id]
            obs["total_stations"] = len(company_stations)

        if "towns" in sections:
            obs["towns"] = [
                {"id": t.id, "name": t.name, "population": t.population, "x": t.x, "y": t.y}
                for t in world.towns.values()
            ]
        elif "top_towns" in sections:
            top_towns = sorted(world.towns.values(), key=lambda t: t.population, reverse=True)[:10]
            obs["top_towns"] = [
                {"id": t.id, "name": t.name, "population": t.population}
                for t in top_towns
            ]
            obs["total_towns"] = len(world.towns)

        if "industries" in sections:
            obs["industries"] = [
                {
                    "id": ind.id, "name": ind.name, "type_name": ind.type_name,
                    "x": ind.x, "y": ind.y, "is_raw": ind.is_raw,
                }
                for ind in world.industries.values()
            ]

        if "subsidies" in sections:
            obs["subsidies"] = [
                {
                    "id": s.id, "cargo_label": s.cargo_label,
                    "src_name": s.src_name, "dst_name": s.dst_name,
                }
                for s in world.subsidies.values()
            ]

        if "routes" in sections:
            obs["routes"] = []

        if "game" in sections:
            obs["game"] = {
                "game_date": game.game_date,
                "tick": game.tick,
                "paused": game.paused,
                "mode": game.mode,
            }

        return obs

    async def _execute(self, actions: list[Any], game_date: int = 0) -> list[dict[str, Any]]:
        """Execute validated actions via GS commands through the admin client."""
        results: list[dict[str, Any]] = []
        cycle_num = self.tracker.cycle_count
        for i, action in enumerate(actions):
            params = {**action.parameters, "company_id": self.config.company_id}
            action_id = f"{self.connection_id}:{cycle_num}:{i}"
            status = ActionStatus.FAILED
            error = ""

            try:
                gs_result = await self.runtime.admin_client.send_gamescript(
                    action.action_type, params,
                )
                if gs_result.get("success"):
                    logger.info(
                        "Agent %s action %s OK: %s",
                        self.config.agent_id, action.action_type, gs_result.get("result", {}),
                    )
                    status = ActionStatus.SUCCESS
                    results.append({"status": "success", "result": gs_result.get("result", {})})
                else:
                    error = gs_result.get("error", "GS returned failure")
                    logger.info(
                        "Agent %s action %s FAILED: %s (params=%s)",
                        self.config.agent_id, action.action_type, error, params,
                    )
                    results.append({"status": "failed", "error": error})
            except Exception as exc:
                error = str(exc)
                logger.warning(
                    "Agent %s action %s failed: %s",
                    self.config.agent_id, action.action_type, exc,
                )
                results.append({"status": "error", "error": error})

            # Record action to DB
            self.runtime.recorder.record_action(
                envelope=ActionEnvelope(
                    action_id=action_id,
                    action_type=action.action_type,
                    parameters=params,
                    company_id=self.config.company_id,
                    metadata={
                        "participant_id": self.config.agent_id,
                        "participant_type": "agent",
                        "game_date": game_date,
                        "submitted_at": datetime.now(timezone.utc).isoformat(),
                    },
                ),
                result=ActionResult(
                    action_id=action_id,
                    status=status,
                    error=error,
                ),
            )

        return results
