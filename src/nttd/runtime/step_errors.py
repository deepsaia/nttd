"""Errors raised by the step barrier.

Its own module so the orchestrator and the API layer can both refer to it without
the API importing the runtime for an exception, or the runtime importing FastAPI to
raise an HTTP error. The route translates it into a 400.
"""

from __future__ import annotations


class StepBatchTooLarge(ValueError):
    """A step carried more actions than the profile's ceiling permits.

    Refused whole rather than truncated: a policy that planned a route as one batch
    should not discover half of it was built.
    """


class NotRegisteredForStepping(LookupError):
    """A company stepped without registering at the barrier first.

    Registration is explicit, via ``POST /step/reset``, because the barrier has to know
    who it is waiting for. Inferring it from the session's company count would stall
    every window on a company whose runner never attached.
    """

    def __init__(self, company_id: int) -> None:
        super().__init__(
            f"Company {company_id} has not entered stepped mode. POST /step/reset "
            "first: the barrier waits for every registered stepper, so it has to be "
            "told which companies are playing."
        )
        self.company_id = company_id


class AlreadyWaitingAtBarrier(RuntimeError):
    """A company submitted a second step while its first was still in flight.

    One step per company per window. Two concurrent steps from one company would put
    two batches into a single advance, which is the ceiling bypass in another form.
    """

    def __init__(self, company_id: int) -> None:
        super().__init__(
            f"Company {company_id} already has a step in flight. Wait for it to "
            "return: one step per company per window."
        )
        self.company_id = company_id
