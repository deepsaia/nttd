"""Base class for nttd agents.

Provides two runtime modes:
- ``run_realtime()``: Async real-time — continuous observe→decide→act loop.
- ``run()``: Heartbeat — wait for server trigger, then observe→decide→act.

Subclass and implement ``decide(context) -> list[GameAction]``.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GameAction:
    """A single GS command to submit."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Everything nttd delivers to an agent on each cycle.

    ``compact`` is the LLM-friendly snapshot from ``GET /state/compact``.
    ``history`` is the last N snapshots kept client-side for trend context.
    """

    compact: dict[str, Any]
    history: list[dict[str, Any]]
    company_id: int
    game_date: int
    cycle_count: int


class AgentBase:
    """Base class for all nttd agents. Subclass and implement decide().

    The only contract::

        def decide(context: AgentContext) -> list[GameAction]    # sync
        async def decide(context: AgentContext) -> list[GameAction]  # or async

    nttd provides the loop — agents focus on observe/decide/act logic.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        session_id: str = "",
        company_id: int = 0,
        agent_id: str | None = None,
    ) -> None:
        from agents.nttd_client import NttdClient

        resolved_id = agent_id or f"agent_{company_id}"
        self.client = NttdClient(
            base_url=base_url,
            session_id=session_id,
            agent_id=resolved_id,
            company_id=company_id,
        )
        self.company_id = company_id
        self.session_id = session_id
        self._cycle_count = 0
        self._agent_logger = logging.getLogger(f"agent.{resolved_id}")

    def observe(self) -> dict[str, Any]:
        """Override this to customize what the agent observes each cycle.

        Default returns the compact snapshot. Subclasses can override to:
        - Fetch only specific entities (towns, vehicles, etc.)
        - Combine compact + targeted GS queries
        - Use the full snapshot instead
        - Build a custom observation from multiple sources

        Example overrides::

            def observe(self):
                # Only fetch towns and company finance
                tools = make_tools(self.client, self.company_id)
                return {
                    "towns": tools.get_towns(),
                    "finance": tools.get_company_finance(),
                }

            def observe(self):
                # Full snapshot (larger, more detailed)
                import requests
                resp = requests.get(f"{self.client._session_url}/state/full", timeout=15)
                return resp.json()
        """
        return self.client.get_compact_snapshot()

    def decide(self, context: AgentContext) -> list[GameAction]:
        """Override this. Return actions to submit.

        May also be defined as async. Sync implementations run in an executor so
        blocking LLM calls do not stall the event loop.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Async real-time mode — primary mode for multiplayer
    # ------------------------------------------------------------------

    async def run_realtime(self, poll_interval: float = 1.0) -> None:
        """Continuous observe→decide→act loop. Game runs without pausing.

        This is the main loop facility provided by nttd. Agents implement
        ``decide()`` and nttd handles the rest:
        1. Fetch compact snapshot
        2. Call ``decide(context)``
        3. Submit all returned actions (batch)
        4. Wait ``poll_interval`` seconds
        5. Repeat

        Args:
            poll_interval: Seconds between observe cycles. Lower = more responsive
                but more API calls. Recommended: 1.0 for LLM agents, 0.2 for RL.
        """
        self.client.register()
        self._agent_logger.info(
            "Real-time mode: connected to %s (session=%s, company=%d)",
            self.client.base_url, self.session_id, self.company_id,
        )

        loop = asyncio.get_event_loop()

        try:
            while True:
                compact = self.observe()
                game_date: int = compact.get("game_date", 0)

                self._history_append(compact)
                self._log_snapshot_received(compact)

                context = AgentContext(
                    compact=compact,
                    history=self.client.get_snapshot_history(5),
                    company_id=self.company_id,
                    game_date=game_date,
                    cycle_count=self._cycle_count,
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

                if actions:
                    batch = [{"action_type": a.action, "params": a.params} for a in actions]
                    try:
                        results = self.client.submit_actions_batch(batch)
                        for i, result in enumerate(results):
                            status = result.get("status", "unknown")
                            if status == "success":
                                self._agent_logger.info("  %s → success", actions[i].action)
                            else:
                                self._agent_logger.warning(
                                    "  %s → %s: %s", actions[i].action, status, result.get("error", "")
                                )
                    except Exception:
                        self._agent_logger.exception("Failed to submit action batch")

                self._cycle_count += 1
                await asyncio.sleep(poll_interval)
        finally:
            await self.client.stop()

    # ------------------------------------------------------------------
    # Heartbeat mode — legacy pause-step mode
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Heartbeat mode: wait for server trigger → observe → decide → submit → repeat."""
        self.client.register()
        await self.client.start_ws()
        self._agent_logger.info(
            "Heartbeat mode: connected to %s (session=%s, company=%d)",
            self.client.base_url, self.session_id, self.company_id,
        )

        loop = asyncio.get_event_loop()

        try:
            while True:
                trigger = await self.client.wait_for_snapshot()
                game_date: int = trigger.get("game_date", 0)

                compact = self.client.get_compact_snapshot()
                history = self.client.get_snapshot_history(5)

                self._log_snapshot_received(compact)

                context = AgentContext(
                    compact=compact,
                    history=history,
                    company_id=self.company_id,
                    game_date=game_date,
                    cycle_count=self._cycle_count,
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
                        self._agent_logger.info("  %s queued (server: %s)", game_action.action, result)
                    except Exception:
                        self._agent_logger.exception("  failed to submit %s", game_action.action)

                self._cycle_count += 1
        finally:
            await self.client.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _history_append(self, compact: dict[str, Any]) -> None:
        """Append compact snapshot to client history deque."""
        self.client._history.append(compact)

    def _log_snapshot_received(self, compact: dict[str, Any]) -> None:
        c = compact.get("company") or {}
        v = compact.get("vehicles") or {}
        routes = compact.get("routes") or []
        subsidies = compact.get("subsidies") or []
        towns = compact.get("top_towns") or []

        self._agent_logger.info(
            "[cycle=%d] snapshot  date=%s  paused=%s",
            self._cycle_count,
            compact.get("game_date", "?"),
            compact.get("paused", "?"),
        )
        if c:
            self._agent_logger.info(
                "  company: balance=%s  loan=%s  income=%s  value=%s",
                f"{c.get('balance', 0):,}",
                f"{c.get('loan', 0):,}",
                f"{c.get('income', 0):,}",
                f"{c.get('company_value', 0):,}",
            )
        self._agent_logger.info(
            "  vehicles=%d (%s)  stations=%d  routes=%d  subsidies=%d",
            v.get("total", 0),
            ", ".join(f"{t}x{n}" for t, n in v.get("by_type", {}).items()) or "none",
            compact.get("total_stations", 0),
            compact.get("total_routes", 0),
            len(subsidies),
        )
        if routes:
            for r in routes[:3]:
                self._agent_logger.info(
                    "  route: %s  stations=%s  vehicles=%d  profit=%s/yr",
                    r.get("vehicle_type", "?"),
                    "->".join(str(s) for s in r.get("station_ids", [])),
                    r.get("vehicle_count", 0),
                    f"{r.get('total_profit_this_year', 0):,}",
                )
        if towns:
            self._agent_logger.info(
                "  top towns: %s",
                "  ".join(f"{t.get('name', '?')} (pop {t.get('population', 0):,})" for t in towns),
            )

    def _log_actions_submitted(self, actions: list[GameAction]) -> None:
        if not actions:
            self._agent_logger.info("  -> no actions this cycle")
            return
        self._agent_logger.info("  -> submitting %d action(s):", len(actions))
        for a in actions:
            self._agent_logger.info("    * %s  %s", a.action, a.params or "")
