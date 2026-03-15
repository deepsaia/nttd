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
    """Everything an agent needs to make a decision."""

    compact: dict[str, Any]
    history: list[dict[str, Any]]
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

    def decide(self, context: AgentContext) -> list[GameAction]:
        """Override this. Return actions to submit during the heartbeat window.

        May also be defined as async. Sync implementations run in an executor so
        blocking LLM calls do not stall the event loop.
        """
        raise NotImplementedError

    async def run(self) -> None:
        """Connect, then loop: wait for snapshot → build context → decide → submit."""
        self.client.register()
        await self.client.start_ws()
        logger.info("Agent %s running for company %d", self.client.agent_id, self.company_id)

        loop = asyncio.get_event_loop()

        try:
            while True:
                snapshot = await self.client.wait_for_snapshot()
                compact = self.client.get_compact_snapshot()
                history_snaps = self.client.get_snapshot_history(5)
                history = [s.model_dump() for s in history_snaps]

                context = AgentContext(
                    compact=compact,
                    history=history,
                    company_id=self.company_id,
                    game_date=snapshot.game.game_date,
                    heartbeat_count=self._heartbeat_count,
                )

                try:
                    if inspect.iscoroutinefunction(self.decide):
                        actions = await self.decide(context)
                    else:
                        actions = await loop.run_in_executor(None, self.decide, context)
                except Exception:
                    logger.exception("decide() raised an exception")
                    actions = []

                for game_action in actions:
                    try:
                        self.client.submit_heartbeat_action(
                            action=game_action.action,
                            params=game_action.params,
                        )
                    except Exception:
                        logger.exception("Failed to submit action: %s", game_action.action)

                self._heartbeat_count += 1
        finally:
            await self.client.stop()
