"""Per-connection telemetry tracker for gameloop agent cycles."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from nttd.gameloop.schemas import CycleRecord

logger = logging.getLogger(__name__)

_MAX_RECENT_CYCLES = 100


class ConnectionTracker:
    """Tracks per-cycle metrics for a single agent connection.

    Maintains aggregate counters and a rolling window of recent CycleRecords.
    """

    def __init__(self, connection_id: str, session_id: str) -> None:
        self.connection_id = connection_id
        self.session_id = session_id
        self.cycle_count: int = 0
        self.total_actions: int = 0
        self.successful_actions: int = 0
        self.failed_actions: int = 0
        self.total_observe_ms: float = 0.0
        self.total_decide_ms: float = 0.0
        self.total_execute_ms: float = 0.0
        self.total_cycle_ms: float = 0.0
        self.last_error: str = ""
        self.recent_cycles: deque[CycleRecord] = deque(maxlen=_MAX_RECENT_CYCLES)

        self._cycle_start: float = 0.0
        self._observe_start: float = 0.0
        self._decide_start: float = 0.0
        self._execute_start: float = 0.0

        self._current_observe_ms: float = 0.0
        self._current_decide_ms: float = 0.0
        self._current_execute_ms: float = 0.0
        self._current_obs_bytes: int = 0

    def start_cycle(self) -> None:
        """Mark the beginning of a new cycle."""
        self._cycle_start = time.monotonic()

    def start_observe(self) -> None:
        """Mark the start of the observation phase."""
        self._observe_start = time.monotonic()

    def end_observe(self, observation: dict[str, Any]) -> None:
        """Record observation completion and size."""
        elapsed = (time.monotonic() - self._observe_start) * 1000
        self._current_observe_ms = elapsed
        self.total_observe_ms += elapsed
        self._current_obs_bytes = len(str(observation))

    def start_decide(self) -> None:
        """Mark the start of the LLM decision phase."""
        self._decide_start = time.monotonic()

    def end_decide(self) -> None:
        """Record decision completion."""
        elapsed = (time.monotonic() - self._decide_start) * 1000
        self._current_decide_ms = elapsed
        self.total_decide_ms += elapsed

    def start_execute(self) -> None:
        """Mark the start of the action execution phase."""
        self._execute_start = time.monotonic()

    def end_execute(self) -> None:
        """Record execution completion."""
        elapsed = (time.monotonic() - self._execute_start) * 1000
        self._current_execute_ms = elapsed
        self.total_execute_ms += elapsed

    def end_cycle(
        self,
        game_date: int,
        actions_proposed: int,
        actions_executed: int,
        actions_succeeded: int,
        actions_failed: int,
    ) -> CycleRecord:
        """Complete the cycle and produce a CycleRecord."""
        total_ms = (time.monotonic() - self._cycle_start) * 1000
        self.total_cycle_ms += total_ms
        self.cycle_count += 1
        self.total_actions += actions_proposed
        self.successful_actions += actions_succeeded
        self.failed_actions += actions_failed

        record = CycleRecord(
            connection_id=self.connection_id,
            session_id=self.session_id,
            cycle_number=self.cycle_count,
            game_date=game_date,
            observe_ms=round(self._current_observe_ms, 1),
            decide_ms=round(self._current_decide_ms, 1),
            execute_ms=round(self._current_execute_ms, 1),
            total_ms=round(total_ms, 1),
            actions_proposed=actions_proposed,
            actions_executed=actions_executed,
            actions_succeeded=actions_succeeded,
            actions_failed=actions_failed,
            observation_size_bytes=self._current_obs_bytes,
        )
        self.recent_cycles.append(record)
        return record

    def record_error(self, error: str) -> None:
        """Record an error that occurred during the cycle."""
        self.last_error = error
        logger.warning("Connection %s cycle error: %s", self.connection_id, error)

    @property
    def avg_cycle_ms(self) -> float:
        """Average cycle time in milliseconds."""
        return self.total_cycle_ms / self.cycle_count if self.cycle_count else 0.0

    @property
    def avg_decide_ms(self) -> float:
        """Average LLM decision time in milliseconds."""
        return self.total_decide_ms / self.cycle_count if self.cycle_count else 0.0

    def summary(self) -> dict[str, Any]:
        """Aggregate metrics as a dict."""
        return {
            "connection_id": self.connection_id,
            "cycle_count": self.cycle_count,
            "total_actions": self.total_actions,
            "successful_actions": self.successful_actions,
            "failed_actions": self.failed_actions,
            "avg_cycle_ms": round(self.avg_cycle_ms, 1),
            "avg_decide_ms": round(self.avg_decide_ms, 1),
            "last_error": self.last_error,
        }
