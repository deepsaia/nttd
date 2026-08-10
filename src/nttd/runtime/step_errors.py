"""Errors raised by the step gate.

Its own module so the orchestrator and the API layer can both refer to it without
the API importing the runtime for an exception, or the runtime importing FastAPI to
raise an HTTP error. The route translates it into a 409.
"""

from __future__ import annotations


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
