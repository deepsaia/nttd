"""Fairness parameters: the pacing and budget limits a scenario imposes.

These decide how much a contestant is allowed to do, so they cannot be declared by
the contestant. They were once fields on the agent config an agent supplied at
registration, which meant every contestant set its own budget -- ``poll_interval``
had a 0.5s floor, so one agent could take 20x the decisions of another and still be
"playing the same scenario", and the bundled configs shipped
``max_actions_per_cycle`` as 5, 10, and 50.

They are now owned by the scenario. Since nttd no longer runs anybody's agent, the
limits bind at the only place a contestant can reach: the sliding-window
``ActionBudget`` on the REST path, built from ``poll_interval`` and
``max_actions_per_cycle`` here. The effective values are recorded in the result, so a
reader can see what the run was actually held to.

Enforced only for a scored session. Local experimentation and scenario authoring have
nothing to protect.

Note what is deliberately NOT bounded: information. A scored run receives the
complete entitled game state and the contestant decides what matters, because
filtering is part of the task. That is why ``observation_mode`` is pinned to ``full``
rather than being configurable. What is bounded is the RATE and the ACTION budget,
which is what a human is bounded by.
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
# A scored run always receives the complete entitled game state. Filtering is the
# agent's job -- deciding what matters is part of the task. This is deliberately
# not configurable: a narrower class would make two runs in the same tier
# incomparable on information while appearing comparable.
SCORED_OBSERVATION_MODE = "full"
_DEFAULT_OBSERVATION_MODE = SCORED_OBSERVATION_MODE

# Bounds enforced here as well as in strict scenario validation, because the lenient
# path (nttd session create, POST /admin/sessions/new) only WARNS about an
# out-of-range value and then emits it verbatim. Left unclamped, poll_interval = 0.0
# produced a sleepless busy loop and max_history_cycles = -1 raised ValueError from
# collections.deque(maxlen=-1) at agent registration, surfacing as an opaque 409.
#
# A floor rather than a fallback: substituting the default would silently run a
# different scenario, whereas clamping keeps the author's intent as far as it is
# expressible and logs the correction.
_LIMITS: dict[str, tuple[float, float]] = {
    "poll_interval": (0.5, 3600.0),
    "max_actions_per_cycle": (1, 200),
    "max_history_cycles": (0, 1000),
    "llm_timeout_seconds": (1.0, 3600.0),
}


@dataclass(frozen=True)
class FairnessConfig:
    """Operator-owned limits applied to every contestant in a session.

    Attributes:
        poll_interval: Seconds between agent cycles in real-time mode. The decision
            rate, and therefore the main axis on which a fast agent could otherwise
            out-act a slow one for reasons unrelated to policy quality.
        max_actions_per_cycle: Soft ceiling on actions per decision. Agents need
            not spend it.
        max_history_cycles: How many past cycles a contestant should carry as
            context. Declared rather than enforced: the contestant's loop runs in
            its own process, so nttd cannot police what it remembers. Recorded so a
            reader knows the intended limit.
        llm_timeout_seconds: Intended cap on a single decision, likewise declared
            rather than enforced. What actually bounds a run is its end condition.
        observation_mode: Which snapshot class a scored agent receives. Always
            ``full``: a scored run hands over the complete entitled game state and
            leaves filtering to the agent, because deciding what matters is part of
            the task rather than something the platform should pre-empt. Pinning a
            narrower class would also make two runs incomparable on information
            while looking comparable.
        enforced: Whether the limits actually bind. True for a scored session;
            False for local experimentation and scenario authoring, which have no
            comparability to protect.
    """

    poll_interval: float = _DEFAULT_POLL_INTERVAL
    max_actions_per_cycle: int = _DEFAULT_MAX_ACTIONS
    max_history_cycles: int = _DEFAULT_MAX_HISTORY
    llm_timeout_seconds: float = _DEFAULT_LLM_TIMEOUT
    observation_mode: str = _DEFAULT_OBSERVATION_MODE
    enforced: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def from_settings(settings: dict[str, str]) -> FairnessConfig:
    """Build a FairnessConfig from the internal ``_fair_*`` settings keys.

    Enforcement is tied to the session being scored rather than to a separate
    switch: a scored run must be bounded by its task, and an unscored one has
    nothing to protect.
    """
    def _clamp(field: str, value: float) -> float:
        low, high = _LIMITS[field]
        clamped = min(max(value, low), high)
        if clamped != value:
            logger.warning(
                "fairness.%s = %s is outside [%s, %s]; clamped to %s",
                field, value, low, high, clamped,
            )
        return clamped

    def _float(key: str, field: str, default: float) -> float:
        raw = settings.get(key)
        try:
            value = float(raw) if raw not in (None, "") else default
        except ValueError:
            logger.warning("Ignoring non-numeric %s=%r", key, raw)
            value = default
        return _clamp(field, value)

    def _int(key: str, field: str, default: int) -> int:
        raw = settings.get(key)
        try:
            value = int(raw) if raw not in (None, "") else default
        except ValueError:
            logger.warning("Ignoring non-integer %s=%r", key, raw)
            value = default
        return int(_clamp(field, value))

    return FairnessConfig(
        poll_interval=_float("_fair_poll_interval", "poll_interval", _DEFAULT_POLL_INTERVAL),
        max_actions_per_cycle=_int(
            "_fair_max_actions", "max_actions_per_cycle", _DEFAULT_MAX_ACTIONS,
        ),
        max_history_cycles=_int(
            "_fair_max_history", "max_history_cycles", _DEFAULT_MAX_HISTORY,
        ),
        llm_timeout_seconds=_float(
            "_fair_llm_timeout", "llm_timeout_seconds", _DEFAULT_LLM_TIMEOUT,
        ),
        # Not read from settings: a scored run always observes fully.
        observation_mode=SCORED_OBSERVATION_MODE,
        enforced=settings.get("_scored") == "1",
    )
