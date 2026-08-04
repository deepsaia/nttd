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
