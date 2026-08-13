"""Errors raised by the step gate.

Its own module so the orchestrator and the API layer can both refer to it without
the API importing the runtime for an exception, or the runtime importing FastAPI to
raise an HTTP error. The route translates it into a 409.
"""

from __future__ import annotations


class ScenarioIsNotStepped(PermissionError):
    """Stepping was asked for on a scenario that declares real-time play.

    The scenario decides the mode, not the contestant, because the two measure different
    things and the difference is the point of having both. In real time, thinking costs
    game days, so speed is part of what is scored. In stepped play the world is paused
    between steps and deliberation is free, which is what makes a language model policy
    comparable with a trained one on decision quality rather than latency.

    A contestant able to switch would take unlimited thinking time on a scenario scored on
    the assumption it had not, and land on the same leaderboard as entrants who did.
    Refused rather than recorded, so the declared mode and the played mode cannot differ
    and nothing downstream has to reconcile them.
    """

    def __init__(self, mode: str) -> None:
        super().__init__(
            f"This scenario is played in real time, not in steps: its runtime mode is "
            f"{mode!r}. The world runs on its own clock, so there is nothing to step. "
            "Submit actions with POST /v1/participant/sessions/{session_id}/actions/submit "
            "and observe with GET /v1/participant/sessions/{session_id}/state/full whenever "
            "you are ready."
        )
        self.mode = mode


class NotRegisteredForStepping(LookupError):
    """A company stepped without entering stepped mode first.

    Registration is explicit, via ``POST /step/reset``, rather than inferred from the
    session's company count. A ``/step`` against a session that never entered stepped
    mode is a mistake worth naming: served silently it would advance the world, and the
    caller would have a running clock it did not know it had started.
    """

    def __init__(self, company_id: int) -> None:
        super().__init__(
            f"Company {company_id} has not entered stepped mode. POST /step/reset "
            "first: it pauses the world, registers you as the stepper, and returns the "
            "opening observation."
        )
        self.company_id = company_id


class StepAlreadyInFlight(RuntimeError):
    """A second step arrived while the first was still running.

    Each step advances the world, so two concurrent ones would make "one step" mean one
    or two advances depending on timing. Refused rather than queued: a caller that
    issued two has a bug, and serialising them silently would hide it behind a result
    that looks correct.
    """

    def __init__(self, company_id: int) -> None:
        super().__init__(
            f"Company {company_id} already has a step in flight. Wait for it to return: "
            "each step advances the world, so a second one running alongside would "
            "advance it twice."
        )
        self.company_id = company_id
