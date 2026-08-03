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
    # Refused by the scored-session lock: the action exists and the caller was
    # entitled to ask, but a scored run does not permit it. Distinct from REJECTED
    # so an audit can tell "tried to use an operator power during a scored run"
    # apart from "sent a malformed or unknown action".
    BLOCKED = "blocked"


class ActionResult(BaseModel):
    action_id: str
    status: ActionStatus
    error: str = ""
    changed_entities: dict[str, Any] = Field(default_factory=dict)
