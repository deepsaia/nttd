"""Fairness parameters: the pacing and budget limits a scenario imposes.

These decide how much a contestant is allowed to do, so they cannot be declared by
the contestant. They arrived on ``AgentConfig``, which an agent supplies at
registration, meaning every contestant set their own budget:

  * ``poll_interval`` has a floor of 0.5s, so one agent could take 20x the
    decisions of another polling at 10s and still be "playing the same scenario".
  * ``max_actions_per_cycle`` shipped as 5, 10, and 50 across the bundled configs.
  * ``observation_mode`` spans roughly 0.5 KB to 80 KB, a 160x information spread.

A scored session overrides all of them from the scenario, so the run is bounded by
the task rather than by what the contestant asked for. The effective values are
recorded in the result, so a reader can see what the run was actually held to.

An unscored session leaves contestant values alone: local experimentation and
scenario authoring need to be able to turn the knobs.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Matches the shipped 30-minute configs, which used poll_interval 10.0 and
# max_actions_per_cycle 5. K=15 gives room for a route plus vehicles and orders.
_DEFAULT_POLL_INTERVAL = 10.0
_DEFAULT_MAX_ACTIONS = 15
_DEFAULT_MAX_HISTORY = 10
_DEFAULT_LLM_TIMEOUT = 120.0
_DEFAULT_OBSERVATION_MODE = "compact"


@dataclass(frozen=True)
class FairnessConfig:
    """Operator-owned limits applied to every contestant in a session.

    Attributes:
        poll_interval: Seconds between agent cycles in real-time mode. The decision
            rate, and therefore the main axis on which a fast agent could otherwise
            out-act a slow one for reasons unrelated to policy quality.
        max_actions_per_cycle: Soft ceiling on actions per decision. Agents need
            not spend it.
        max_history_cycles: How many past cycles an agent may carry as context.
        llm_timeout_seconds: Hard cap on a single decision. Prevents one stalled
            contestant holding a session open indefinitely.
        observation_mode: Which observation an agent receives. Fixed per scenario
            so two runs in the same tier see the same world in the same detail.
        enforced: Whether these override contestant-supplied values. True for a
            scored session; False leaves contestant values alone.
    """

    poll_interval: float = _DEFAULT_POLL_INTERVAL
    max_actions_per_cycle: int = _DEFAULT_MAX_ACTIONS
    max_history_cycles: int = _DEFAULT_MAX_HISTORY
    llm_timeout_seconds: float = _DEFAULT_LLM_TIMEOUT
    observation_mode: str = _DEFAULT_OBSERVATION_MODE
    enforced: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def apply_to(self, config: Any) -> dict[str, tuple[Any, Any]]:
        """Overwrite an AgentConfig's fairness fields in place.

        Returns ``{field: (requested, applied)}`` for the fields actually changed.
        Structured rather than formatted, because a caller needs the requested
        values as data: "this contestant asked to run at 0.5s" belongs in the
        result record, and after the mutation it exists nowhere else.

        Does nothing when not enforced.
        """
        if not self.enforced:
            return {}

        overrides = {
            "poll_interval": self.poll_interval,
            "max_actions_per_cycle": self.max_actions_per_cycle,
            "max_history_cycles": self.max_history_cycles,
            "observation_mode": self.observation_mode,
        }
        changed: dict[str, tuple[Any, Any]] = {}
        for field, applied in overrides.items():
            requested = getattr(config, field, None)
            if requested != applied:
                changed[field] = (requested, applied)
                setattr(config, field, applied)
        return changed


def from_settings(settings: dict[str, str]) -> FairnessConfig:
    """Build a FairnessConfig from the internal ``_fair_*`` settings keys.

    Enforcement is tied to the session being scored rather than to a separate
    switch: a scored run must be bounded by its task, and an unscored one has
    nothing to protect.
    """
    def _float(key: str, default: float) -> float:
        raw = settings.get(key)
        try:
            return float(raw) if raw not in (None, "") else default
        except ValueError:
            logger.warning("Ignoring non-numeric %s=%r", key, raw)
            return default

    def _int(key: str, default: int) -> int:
        raw = settings.get(key)
        try:
            return int(raw) if raw not in (None, "") else default
        except ValueError:
            logger.warning("Ignoring non-integer %s=%r", key, raw)
            return default

    return FairnessConfig(
        poll_interval=_float("_fair_poll_interval", _DEFAULT_POLL_INTERVAL),
        max_actions_per_cycle=_int("_fair_max_actions", _DEFAULT_MAX_ACTIONS),
        max_history_cycles=_int("_fair_max_history", _DEFAULT_MAX_HISTORY),
        llm_timeout_seconds=_float("_fair_llm_timeout", _DEFAULT_LLM_TIMEOUT),
        observation_mode=settings.get("_fair_observation_mode") or _DEFAULT_OBSERVATION_MODE,
        enforced=settings.get("_scored") == "1",
    )
