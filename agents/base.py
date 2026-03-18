from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GameAction:
    """A single GS command to submit during the action window."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Everything nttd delivers to an agent on each heartbeat beat.

    nttd pushes the compact snapshot as a lightweight trigger.  The agent is
    free to call whatever additional tools or queries it needs — those are
    implemented in the agent's own framework code, not here.

    ``history`` is the last N full snapshots (oldest first) kept client-side
    by NttdClient for trend/context without requiring extra server calls.
    """

    compact: dict[str, Any]          # compact snapshot — heartbeat trigger + LLM-friendly summary
    history: list[dict[str, Any]]    # last N full snapshots, oldest first
    company_id: int
    game_date: int
    heartbeat_count: int


class AgentBase:
    """Base class for all nttd agents. Subclass and implement decide().

    The only contract:
        def decide(context: AgentContext) -> list[GameAction]   # sync
        async def decide(context: AgentContext) -> list[GameAction]  # or async

    Call run() to enter the game loop: connect → wait for heartbeat → decide → submit → repeat.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        company_id: int = 0,
        agent_id: str | None = None,
    ) -> None:
        from agents.nttd_client import NttdClient  # deferred to avoid circular imports

        resolved_id = agent_id or f"agent_{company_id}"
        self.client = NttdClient(
            base_url=base_url,
            agent_id=resolved_id,
            company_id=company_id,
        )
        self.company_id = company_id
        self._heartbeat_count = 0
        self._agent_logger = logging.getLogger(f"agent.{resolved_id}")

    def decide(self, context: AgentContext) -> list[GameAction]:
        """Override this. Return actions to submit during the heartbeat window.

        May also be defined as async. Sync implementations run in an executor so
        blocking LLM calls do not stall the event loop.
        """
        raise NotImplementedError

    def _log_snapshot_received(self, compact: dict[str, Any]) -> None:
        c = compact.get("company") or {}
        v = compact.get("vehicles") or {}
        routes = compact.get("routes") or []
        subsidies = compact.get("subsidies") or []
        towns = compact.get("top_towns") or []
        stations = compact.get("top_stations") or []

        self._agent_logger.info(
            "[hb=%d] ← snapshot  date=%s  paused=%s",
            self._heartbeat_count,
            compact.get("game_date", "?"),
            compact.get("paused", "?"),
        )
        if c:
            self._agent_logger.info(
                "         company: balance=%s  loan=%s  income=%s  value=%s",
                f"{c.get('balance', 0):,}",
                f"{c.get('loan', 0):,}",
                f"{c.get('income', 0):,}",
                f"{c.get('company_value', 0):,}",
            )
        self._agent_logger.info(
            "         vehicles=%d (%s)  stations=%d  routes=%d  subsidies=%d",
            v.get("total", 0),
            ", ".join(f"{t}×{n}" for t, n in v.get("by_type", {}).items()) or "none",
            compact.get("total_stations", 0),
            compact.get("total_routes", 0),
            len(subsidies),
        )
        if routes:
            for r in routes[:3]:
                self._agent_logger.info(
                    "         route: %s  stations=%s  vehicles=%d  profit=%s/yr",
                    r.get("vehicle_type", "?"),
                    "→".join(str(s) for s in r.get("station_ids", [])),
                    r.get("vehicle_count", 0),
                    f"{r.get('total_profit_this_year', 0):,}",
                )
        if subsidies:
            for s in subsidies[:3]:
                self._agent_logger.info(
                    "         subsidy: %s  %s→%s  value=%s  expires=%dyr",
                    s.get("cargo_label", "?"),
                    s.get("src_name", "?"),
                    s.get("dst_name", "?"),
                    f"{s.get('value', 0):,}",
                    s.get("remaining_years", 0),
                )
        if towns:
            self._agent_logger.info(
                "         top towns: %s",
                "  ".join(f"{t.get('name','?')} (pop {t.get('population',0):,})" for t in towns),
            )
        if stations:
            self._agent_logger.info(
                "         busy stations: %s",
                "  ".join(f"{s.get('name','?')} ({s.get('cargo_total',0)} waiting)" for s in stations),
            )

    def _log_actions_submitted(self, actions: list[GameAction]) -> None:
        if not actions:
            self._agent_logger.info("         → no actions this heartbeat")
            return
        self._agent_logger.info("         → submitting %d action(s):", len(actions))
        for a in actions:
            self._agent_logger.info("           • %s  %s", a.action, a.params or "")

    async def run(self) -> None:
        """Connect, then loop: wait for snapshot → log input → decide → log+submit output."""
        self.client.register()
        await self.client.start_ws()
        self._agent_logger.info(
            "connected to %s  (company=%d)", self.client.base_url, self.company_id
        )

        loop = asyncio.get_event_loop()

        try:
            while True:
                # Wait for lightweight heartbeat trigger from server WebSocket
                trigger = await self.client.wait_for_snapshot()
                game_date: int = trigger.get("game_date", 0)

                # Fetch compact snapshot via HTTP (the agent's primary view of state)
                compact = self.client.get_compact_snapshot()
                # History: last N trigger dicts (game_date, counts) for trend context
                history = self.client.get_snapshot_history(5)

                self._log_snapshot_received(compact)

                context = AgentContext(
                    compact=compact,
                    history=history,
                    company_id=self.company_id,
                    game_date=game_date,
                    heartbeat_count=self._heartbeat_count,
                )

                try:
                    if inspect.iscoroutinefunction(self.decide):
                        actions = await self.decide(context)
                    else:
                        actions = await loop.run_in_executor(None, self.decide, context)
                except Exception:
                    self._agent_logger.exception("decide() raised an exception")
                    actions = []

                self._log_actions_submitted(actions)

                for game_action in actions:
                    try:
                        result = self.client.submit_heartbeat_action(
                            action=game_action.action,
                            params=game_action.params,
                        )
                        self._agent_logger.info(
                            "           ✓ %s queued  (server: %s)",
                            game_action.action,
                            result,
                        )
                    except Exception:
                        self._agent_logger.exception(
                            "           ✗ failed to submit %s", game_action.action
                        )

                self._heartbeat_count += 1
        finally:
            await self.client.stop()
