"""Fairness limits: how much a contestant may do in one decision.

One knob, ``max_actions_per_decision``: the ceiling on a single submission. It applies
to both modes, since a submission is variable-length in either -- real-time, whatever
batch a contestant has decided on; stepped, whatever it accumulated while paused and
flushes on stepping.

What differs between the modes is the denominator, not the ceiling. Stepped play has a
natural one, the step, with ``max_heartbeats`` bounding how many there are; real-time
has none, which is why a wall-clock window was tried here and removed. How many of its
15 a policy spends per step is the policy's own optimisation problem, which is what an
RL or ES entry is being scored on.

It is operator policy, so it lives in ``config/benchmark/profile.conf`` rather than in
a scenario. Left to the scenario author it would vary between tasks that are otherwise
identical, and a contestant writing their own conforming scenario would be setting
their own budget -- which is exactly what moving these off the agent config fixed.

What is deliberately NOT here:

  * A RATE limit. There was one, a sliding wall-clock window, and it was removed: at
    15 actions per 10s a 30-minute real-time run allowed about 2,700 actions against
    about 900 for the same task played stepped, so it made the modes threefold
    incomparable while claiming to make them fair. It also bounded rhythm rather than
    work.

  * An LLM TIMEOUT or a HISTORY DEPTH. Both are client concerns. The contestant's loop
    runs in its own process, so nttd cannot police how long it thinks or what it
    remembers; stating an unenforceable suggestion as a limit misleads a reader of the
    result. What bounds a run is its end condition.

  * OBSERVATION. A scored run receives the complete entitled game state and the
    contestant decides what matters, because filtering is part of the task.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from nttd.config.benchmark_profile import active_profile

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ACTIONS = 15

# A scored run always receives the complete entitled game state. Not configurable: a
# narrower class would make two runs incomparable on information while appearing
# comparable, and would not stop a contestant pulling the same data through queries.
SCORED_OBSERVATION_MODE = "full"


@dataclass(frozen=True)
class FairnessConfig:
    """The limits a scored run is held to.

    Attributes:
        max_actions_per_decision: Actions permitted in one submission. A soft
            ceiling: a contestant need not spend it, and several loops sharing one
            company share it rather than each getting it. Enough for a route -- loan,
            two stations, a connection, a vehicle, orders -- with room to spare.
        observation_mode: Always ``full``. Present because the result records it, so a
            reader can see that information was not bounded.
        enforced: Whether the limit binds. True for a scored session; False for local
            experimentation and scenario authoring, which have nothing to protect.
    """

    max_actions_per_decision: int = _DEFAULT_MAX_ACTIONS
    observation_mode: str = SCORED_OBSERVATION_MODE
    enforced: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def from_settings(settings: dict[str, str]) -> FairnessConfig:
    """Build the limits for a session.

    The value comes from the benchmark profile, not from the session settings: a
    scenario cannot set its own budget. Only ``_scored`` is read here, because
    enforcement is tied to the session being scored rather than to a separate switch
    -- a scored run must be bounded by its task, and an unscored one has nothing to
    protect.
    """
    raw = active_profile().fairness.get("max_actions_per_decision", _DEFAULT_MAX_ACTIONS)
    try:
        per_decision = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Profile fairness.max_actions_per_decision = %r is not an integer; using %d",
            raw, _DEFAULT_MAX_ACTIONS,
        )
        per_decision = _DEFAULT_MAX_ACTIONS

    return FairnessConfig(
        max_actions_per_decision=per_decision,
        observation_mode=SCORED_OBSERVATION_MODE,
        enforced=settings.get("_scored") == "1",
    )
