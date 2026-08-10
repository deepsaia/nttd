from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    # A compound build that laid part of what was asked. Distinct from FAILED because
    # the world moved and was paid for, and distinct from SUCCESS because the result is
    # not usable: a route with a gap is not a route. Reporting either one alone loses
    # half the story, and a policy scoring on outcome needs to tell them apart.
    PARTIAL = "partial"
    # Refused by the scored-session lock: the action exists and the caller was
    # entitled to ask, but a scored run does not permit it. Distinct from REJECTED
    # so an audit can tell "tried to use an operator power during a scored run"
    # apart from "sent a malformed or unknown action".
    BLOCKED = "blocked"


class ActionResult(BaseModel):
    """What happened to one submitted action.

    ``error`` used to carry everything: OpenTTD error names, nttd's own sentences, and
    Squirrel exception text, with nothing to tell them apart. RL and ES need a discrete
    failure signal rather than a string to pattern-match on, so the machine-readable part
    is now separate from the prose.

    Attributes:
        action_type: Which action this was. Carried so a caller reading a batch of
            results does not have to correlate on action_id to learn which of its
            actions was refused. Empty on a result read back from storage, where the
            action log already names it.
        error: One line, for a person.
        error_code: OpenTTD's error number, when the game was the one that refused.
            Absent for nttd's own precondition failures, and that absence is what
            identifies them.
        error_name: The stable constant, such as ``ERR_NOT_ENOUGH_CASH``.
        error_category: Which family it belongs to, such as ``tile`` or ``rail``.
    """

    action_id: str
    action_type: str = ""
    status: ActionStatus
    error: str = ""
    error_code: int | None = None
    error_name: str = ""
    error_category: str = ""
    changed_entities: dict[str, Any] = Field(default_factory=dict)
