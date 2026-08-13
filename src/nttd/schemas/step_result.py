"""What one step of the barrier returns.

Deliberately not shaped like a Gym tuple. Reward is absent because nttd does not
define one: a reward function is the contestant's choice of what to optimise, and
baking one in would make every RL entry optimise the platform's opinion rather than
its own. The env computes reward from the observation, which is also what lets two
policies with different reward shaping still be compared on the same score.

``truncated`` is likewise absent. Gym distinguishes termination from truncation, but
the distinction belongs to the env's own step budget, which is the contestant's,
rather than to the server, which only knows whether an end condition fired.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from nttd.schemas.action_result import ActionResult
from nttd.schemas.snapshot import StateSnapshot

# The only keys an action entry in a step batch may carry. Everything an action needs
# goes inside `params`, which is what the MCP step tool and the REST route both send.
_ACTION_KEYS = frozenset({"action", "params"})


class StepResult(BaseModel):
    """The outcome of advancing the world by one step.

    Attributes:
        snapshot: The world after the step, observed while paused so it is
            consistent rather than caught mid-tick.
        step: How many steps this session has taken, counting from 1.
        days_advanced: Game-days the world moved. Recorded per step because a
            scenario may change the interval, and a reader reconstructing the run
            needs to know what a step was worth.
        terminated: Whether an end condition fired. The run is over; further steps
            will not advance a finished session.
        end_reason: Which condition, empty while the run continues.
        action_results: What happened to each action in the batch this step flushed, in
            the order submitted. Empty for a step that submitted nothing.

            Present because the observation alone cannot answer it. A refused action
            often changes nothing at all, so a world that looks unchanged is
            indistinguishable from one where the action was never sent, and a policy
            cannot learn not to repeat it. The outcomes were always computed and written
            to the action log; they were simply not handed back.

    A ``steppers`` list used to sit here, naming the companies whose actions went into
    one advance. It answered a question that can no longer be asked: a session holds one
    contestant, so a step is always that company's and the field said only what the
    token already did.
    """

    snapshot: StateSnapshot
    step: int = 0
    days_advanced: int = 0
    terminated: bool = False
    end_reason: str = ""
    action_results: list[ActionResult] = Field(default_factory=list)


class StepRequest(BaseModel):
    """A contestant's step: a batch of actions, then advance.

    Attributes:
        actions: Variable length, because a step is not one action. A policy that
            wants to lay a whole route in one step may, and one that wants to act
            once may. There is no ceiling: a stepped run is bounded by how many
            steps it takes and how many game-days each advances, both fixed by the
            scenario, so a larger batch buys no more world than anyone else gets.
        days: Override the scenario's step size. Present for experimentation, and
            ignored for a scored run, where the step size is part of the task.
    """

    actions: list[dict] = Field(default_factory=list)
    days: int | None = None

    @field_validator("actions")
    @classmethod
    def _reject_misplaced_parameters(cls, actions: list[dict]) -> list[dict]:
        """Refuse an action whose parameters were not put in ``params``.

        An action is ``{"action": ..., "params": {...}}``. Written flat, as
        ``{"action": ..., "x": 8, "y": 31}``, every field beyond ``action`` used to be
        dropped in silence: ``params`` came out empty and the GameScript then failed on
        the first field it tried to read, answering "the index 'x' does not exist". That
        names neither the real mistake nor where the fields should have gone, and it is
        indistinguishable from genuinely omitting a required argument.

        Dropping a caller's entire parameter set without a word is the worst of the
        available outcomes, so this refuses instead, naming the strays.
        """
        for index, entry in enumerate(actions):
            stray = sorted(set(entry) - _ACTION_KEYS)
            if stray:
                raise ValueError(
                    f"action {index} ({entry.get('action') or 'unnamed'}) has "
                    f"{', '.join(stray)} at the top level. Action parameters belong in "
                    f"`params`: {{\"action\": ..., \"params\": {{...}}}}"
                )
        return actions
