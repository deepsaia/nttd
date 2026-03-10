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


class ActionResult(BaseModel):
    action_id: str
    status: ActionStatus
    error: str = ""
    changed_entities: dict[str, Any] = Field(default_factory=dict)
